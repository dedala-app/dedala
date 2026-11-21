// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Markdown read with pulldown-cmark into the same tree as Org: headings
//! nest as `headline`s over `section`s, lists hold `item`s with their
//! `checkbox`, fenced code is a `src-block`, front matter the `keywords`.

use pulldown_cmark::{CodeBlockKind, Event, HeadingLevel, LinkType, MetadataBlockKind, Options, Parser, Tag, TagEnd};
use serde_json::{Map, Value};
use std::ops::Range;

use crate::node::Node;
use crate::text::plain;

pub fn parse(text: &str) -> Node {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_TABLES);
    options.insert(Options::ENABLE_FOOTNOTES);
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TASKLISTS);
    options.insert(Options::ENABLE_YAML_STYLE_METADATA_BLOCKS);
    options.insert(Options::ENABLE_WIKILINKS);
    let mut builder = Builder { text, stack: vec![Frame::new(Node::new("org-data", 0, text.len()))], keywords: Map::new(), metadata: None };
    for (event, range) in Parser::new_ext(text, options).into_offset_iter() {
        builder.event(event, range);
    }
    let mut root = builder.stack.pop().map(|frame| frame.close()).unwrap_or_else(|| Node::new("org-data", 0, text.len()));
    let children = nest(root.children());
    if let Some(title) = builder.keywords.get("TITLE").and_then(Value::as_str) {
        root.set("title", title.to_string());
    }
    root.set("keywords", Value::Object(builder.keywords));
    root.set_children(children);
    root
}

struct Frame {
    node: Node,
    children: Vec<Node>,
    objects: Vec<Node>,
}

impl Frame {
    fn new(node: Node) -> Frame {
        Frame { node, children: vec![], objects: vec![] }
    }

    /// Objects collected straight into an element that holds elements (a
    /// tight list item) become a paragraph of their own.
    fn flush_objects(&mut self) {
        if self.objects.is_empty() {
            return;
        }
        let objects = std::mem::take(&mut self.objects);
        let begin = objects.first().map(Node::begin).unwrap_or(self.node.begin());
        let end = objects.last().map(Node::end).unwrap_or(begin);
        let mut paragraph = Node::new("paragraph", begin, end);
        paragraph.set("text", plain(&objects));
        paragraph.set_children(objects);
        self.children.push(paragraph);
    }

    fn close(mut self) -> Node {
        match self.node.kind() {
            "paragraph" | "table-cell" | "bold" | "italic" | "strike-through" | "link" | "headline" => {
                let objects = std::mem::take(&mut self.objects);
                if self.node.kind() == "headline" {
                    self.node.set("title", plain(&objects));
                    self.node.set_objects(objects);
                } else {
                    if self.node.kind() != "link" || !objects.is_empty() {
                        self.node.set("text", plain(&objects));
                    }
                    if self.node.kind() != "link" || !objects.is_empty() {
                        self.node.set_children(objects);
                    }
                }
                if !self.children.is_empty() {
                    self.node.set_children(self.children);
                }
            }
            "item" => {
                self.flush_objects();
                let text: Vec<String> = self
                    .children
                    .iter()
                    .take_while(|child| child.kind() == "paragraph")
                    .map(|child| child.get("text").as_str().unwrap_or("").to_string())
                    .collect();
                let first = self.children.iter().find(|child| child.kind() == "paragraph");
                let content_begin = first.map(Node::begin).unwrap_or(self.node.end());
                let content_end = self
                    .children
                    .iter()
                    .take_while(|child| child.kind() == "paragraph")
                    .last()
                    .map(Node::end)
                    .unwrap_or(content_begin);
                self.node.set("text", text.join(" "));
                self.node.set("contentBegin", content_begin);
                self.node.set("contentEnd", content_end);
                self.node.set_children(self.children);
            }
            _ => {
                self.flush_objects();
                self.node.set_children(self.children);
            }
        }
        self.node
    }
}

struct Builder<'a> {
    text: &'a str,
    stack: Vec<Frame>,
    keywords: Map<String, Value>,
    metadata: Option<MetadataBlockKind>,
}

impl Builder<'_> {
    fn open(&mut self, node: Node) {
        self.stack.push(Frame::new(node));
    }

    fn close(&mut self) {
        if self.stack.len() < 2 {
            return;
        }
        let frame = self.stack.pop().expect("a frame to close");
        let node = frame.close();
        self.add(node);
    }

    fn add(&mut self, node: Node) {
        let parent = self.stack.last_mut().expect("a parent frame");
        let object = matches!(
            node.kind(),
            "plain-text" | "code" | "bold" | "italic" | "strike-through" | "link" | "footnote-reference" | "line-break" | "export-snippet" | "latex-fragment"
        );
        if object {
            if node.kind() == "plain-text" {
                if let Some(last) = parent.objects.last_mut() {
                    if last.kind() == "plain-text" {
                        let value = format!("{}{}", last.get("value").as_str().unwrap_or(""), node.get("value").as_str().unwrap_or(""));
                        last.set("value", value);
                        last.set("end", node.end());
                        return;
                    }
                }
            }
            parent.objects.push(node);
        } else {
            parent.flush_objects();
            parent.children.push(node);
        }
    }

    fn text_node(&mut self, range: Range<usize>, value: &str) {
        let mut node = Node::new("plain-text", range.start, range.end);
        node.set("value", value.to_string());
        self.add(node);
    }

    fn event(&mut self, event: Event, range: Range<usize>) {
        match event {
            Event::Start(tag) => self.start(tag, range),
            Event::End(tag) => self.end(tag, range),
            Event::Text(text) => {
                if let Some(kind) = self.metadata {
                    self.front_matter(kind, &text);
                } else {
                    self.text_node(range, &text);
                }
            }
            Event::Code(code) => {
                let mut node = Node::new("code", range.start, range.end);
                node.set("value", code.to_string());
                self.add(node);
            }
            Event::InlineMath(math) | Event::DisplayMath(math) => {
                let mut node = Node::new("latex-fragment", range.start, range.end);
                node.set("value", math.to_string());
                self.add(node);
            }
            Event::Html(html) | Event::InlineHtml(html) => {
                let mut node = Node::new(if self.stack.last().map(|frame| frame.node.kind() == "export-block").unwrap_or(false) { "plain-text" } else { "export-snippet" }, range.start, range.end);
                if node.kind() == "export-snippet" {
                    node.set("backend", "html");
                }
                node.set("value", html.to_string());
                self.add(node);
            }
            Event::FootnoteReference(label) => {
                let mut node = Node::new("footnote-reference", range.start, range.end);
                node.set("label", label.to_string());
                self.add(node);
            }
            Event::SoftBreak => self.text_node(range, "\n"),
            Event::HardBreak => self.add(Node::new("line-break", range.start, range.end)),
            Event::Rule => self.add(Node::new("horizontal-rule", range.start, range.end)),
            Event::TaskListMarker(checked) => {
                if let Some(frame) = self.stack.last_mut() {
                    frame.node.set("checkbox", if checked { "on" } else { "off" });
                    frame.node.set("checkboxBegin", range.start);
                    frame.node.set("checkboxEnd", range.start + self.text[range.clone()].trim_end().len());
                }
            }
        }
    }

    fn start(&mut self, tag: Tag, range: Range<usize>) {
        let (begin, end) = (range.start, range.end);
        match tag {
            Tag::Paragraph => self.open(Node::new("paragraph", begin, end)),
            Tag::Heading { level, .. } => {
                let mut node = Node::new("headline", begin, end);
                node.set("level", heading_level(level));
                node.set("tags", Value::Array(vec![]));
                self.open(node);
            }
            Tag::BlockQuote(_) => self.open(Node::new("quote-block", begin, end)),
            Tag::CodeBlock(kind) => {
                let mut node = match kind {
                    CodeBlockKind::Fenced(info) => {
                        let mut node = Node::new("src-block", begin, end);
                        let info = info.to_string();
                        let mut words = info.split_whitespace();
                        if let Some(language) = words.next() {
                            node.set("language", language.to_string());
                        }
                        let parameters = words.collect::<Vec<_>>().join(" ");
                        if !parameters.is_empty() {
                            node.set("parameters", parameters);
                        }
                        node
                    }
                    CodeBlockKind::Indented => Node::new("example-block", begin, end),
                };
                node.set("value", String::new());
                self.open(node);
            }
            Tag::HtmlBlock => {
                let mut node = Node::new("export-block", begin, end);
                node.set("backend", "html");
                self.open(node);
            }
            Tag::List(start) => {
                let mut node = Node::new("plain-list", begin, end);
                node.set("listType", if start.is_some() { "ordered" } else { "unordered" });
                node.set("indent", self.indent(begin));
                self.open(node);
            }
            Tag::Item => {
                let mut node = Node::new("item", begin, end);
                let line = &self.text[begin..end.min(self.text.len())];
                let bullet: String = line.split_whitespace().next().unwrap_or("-").to_string();
                node.set("indent", self.indent(begin));
                if let Some(ordered) = bullet.strip_suffix(['.', ')']) {
                    if ordered.chars().all(|c| c.is_ascii_digit()) {
                        node.set("counter", ordered.to_string());
                    }
                }
                node.set("bullet", bullet);
                self.open(node);
            }
            Tag::FootnoteDefinition(label) => {
                let mut node = Node::new("footnote-definition", begin, end);
                node.set("label", label.to_string());
                self.open(node);
            }
            Tag::DefinitionList => {
                let mut node = Node::new("plain-list", begin, end);
                node.set("listType", "descriptive");
                self.open(node);
            }
            Tag::DefinitionListTitle => self.open(Node::new("item", begin, end)),
            Tag::DefinitionListDefinition => self.open(Node::new("paragraph", begin, end)),
            Tag::Table(_) => {
                let mut node = Node::new("table", begin, end);
                node.set("tableType", "org");
                node.set("hasHeader", true);
                self.open(node);
            }
            Tag::TableHead | Tag::TableRow => {
                let mut node = Node::new("table-row", begin, end);
                node.set("rowType", "standard");
                self.open(node);
            }
            Tag::TableCell => self.open(Node::new("table-cell", begin, end)),
            Tag::Emphasis => self.open(Node::new("italic", begin, end)),
            Tag::Strong => self.open(Node::new("bold", begin, end)),
            Tag::Strikethrough => self.open(Node::new("strike-through", begin, end)),
            Tag::Superscript => self.open(Node::new("superscript", begin, end)),
            Tag::Subscript => self.open(Node::new("subscript", begin, end)),
            Tag::Link { link_type, dest_url, .. } | Tag::Image { link_type, dest_url, .. } => {
                let mut node = Node::new("link", begin, end);
                let raw = dest_url.to_string();
                let (kind, path) = match raw.split_once(':') {
                    Some((scheme, rest)) if !scheme.is_empty() && !scheme.contains('/') && scheme.chars().all(|c| c.is_ascii_alphanumeric() || c == '+' || c == '-' || c == '.') => {
                        (scheme.to_lowercase(), rest.to_string())
                    }
                    _ if matches!(link_type, LinkType::WikiLink { .. }) => ("fuzzy".to_string(), raw.clone()),
                    _ => ("file".to_string(), raw.clone()),
                };
                node.set("linkType", kind);
                node.set("path", path);
                node.set("rawLink", raw);
                if range.start < self.text.len() && self.text[begin..].starts_with('!') {
                    node.set("isImage", true);
                }
                self.open(node);
            }
            Tag::MetadataBlock(kind) => {
                self.metadata = Some(kind);
            }
        }
    }

    fn end(&mut self, tag: TagEnd, range: Range<usize>) {
        match tag {
            TagEnd::MetadataBlock(_) => self.metadata = None,
            TagEnd::CodeBlock | TagEnd::HtmlBlock => {
                let frame = self.stack.pop().expect("an open block");
                let mut node = frame.node;
                let value: String = frame.objects.iter().map(|object| object.get("value").as_str().unwrap_or("")).collect();
                node.set("value", value);
                node.set("end", range.end);
                self.add(node);
            }
            TagEnd::Heading(_) => {
                if let Some(frame) = self.stack.last_mut() {
                    let level = frame.node.get("level").as_u64().unwrap_or(1);
                    let _ = level;
                }
                self.close();
            }
            _ => self.close(),
        }
    }

    fn front_matter(&mut self, kind: MetadataBlockKind, text: &str) {
        let _ = kind;
        for line in text.lines() {
            let Some((key, value)) = line.split_once(':') else { continue };
            let key = key.trim();
            if key.is_empty() || key.starts_with(' ') || key.starts_with('-') {
                continue;
            }
            let value = value.trim().trim_matches('"').trim_matches('\'').to_string();
            self.keywords.insert(key.to_uppercase(), Value::String(value));
        }
    }

    fn indent(&self, at: usize) -> usize {
        let line_start = self.text[..at].rfind('\n').map(|found| found + 1).unwrap_or(0);
        self.text[line_start..at].chars().count()
    }
}

fn heading_level(level: HeadingLevel) -> u64 {
    match level {
        HeadingLevel::H1 => 1,
        HeadingLevel::H2 => 2,
        HeadingLevel::H3 => 3,
        HeadingLevel::H4 => 4,
        HeadingLevel::H5 => 5,
        HeadingLevel::H6 => 6,
    }
}

/// Markdown's flat run of headings and blocks folded into Org's shape: a
/// headline holds a section of what follows it and the headlines below its
/// level, the text before the first heading a section of the root.
fn nest(flat: Vec<Node>) -> Vec<Node> {
    let mut out: Vec<Node> = Vec::new();
    let mut leading: Vec<Node> = Vec::new();
    let mut stack: Vec<(u64, Node, Vec<Node>, Vec<Node>)> = Vec::new();

    fn finish(stack: &mut Vec<(u64, Node, Vec<Node>, Vec<Node>)>, out: &mut Vec<Node>) {
        let (_, mut headline, blocks, subs) = stack.pop().expect("a headline");
        let mut children = Vec::new();
        if !blocks.is_empty() {
            let begin = blocks.first().map(Node::begin).unwrap_or(0);
            let end = blocks.last().map(Node::end).unwrap_or(begin);
            let mut section = Node::new("section", begin, end);
            section.set_children(blocks);
            children.push(section);
        }
        children.extend(subs);
        if let Some(last) = children.last() {
            let end = last.end().max(headline.end());
            headline.set("end", end);
        }
        headline.set_children(children);
        match stack.last_mut() {
            Some((_, _, _, subs)) => subs.push(headline),
            None => out.push(headline),
        }
    }

    for node in flat {
        if node.kind() == "headline" {
            let level = node.get("level").as_u64().unwrap_or(1);
            while stack.last().map(|(open, ..)| *open >= level).unwrap_or(false) {
                finish(&mut stack, &mut out);
            }
            stack.push((level, node, vec![], vec![]));
        } else if let Some((_, _, blocks, subs)) = stack.last_mut() {
            if subs.is_empty() {
                blocks.push(node);
            } else {
                blocks.push(node);
            }
        } else {
            leading.push(node);
        }
    }
    while !stack.is_empty() {
        finish(&mut stack, &mut out);
    }
    if !leading.is_empty() {
        let begin = leading.first().map(Node::begin).unwrap_or(0);
        let end = leading.last().map(Node::end).unwrap_or(begin);
        let mut section = Node::new("section", begin, end);
        section.set_children(leading);
        out.insert(0, section);
    }
    out
}
