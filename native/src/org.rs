// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Org read with orgize, each node written in org-element's words: a
//! `headline` carries its planning and properties, a `plain-list` its
//! `item`s with their `checkbox`, a `paragraph` its objects.

use orgize::ast::{
    AffiliatedKeyword, Clock, Comment, Drawer, Entity, ExportBlock, FixedWidth, Headline, InlineCall, InlineSrc, Keyword, Link, List,
    ListItem, Macros, OrgTable, OrgTableRow, Snippet, SourceBlock, SpecialBlock, Timestamp, TodoType,
};
use orgize::rowan::ast::AstNode;
use orgize::rowan::NodeOrToken;
use orgize::{ParseConfig, SyntaxElement, SyntaxKind, SyntaxNode};
use serde_json::{json, Map, Value};
use SyntaxKind::*;

use crate::node::Node;
use crate::text::plain;

const TODO: [&str; 7] = ["TODO", "NEXT", "STARTED", "WAITING", "HOLD", "SOMEDAY", "PROJ"];
const DONE: [&str; 4] = ["DONE", "CANCELLED", "CANCELED", "KILL"];

pub fn parse(text: &str) -> Node {
    let (todo, done) = keywords(text);
    let config = ParseConfig { todo_keywords: (todo, done), ..Default::default() };
    let org = config.parse(text);
    let document = org.document();
    let syntax = document.syntax();
    let mut root = Node::new("org-data", 0, text.len());
    let mut file_keywords: Map<String, Value> = Map::new();
    let mut children = Vec::new();
    for child in syntax.children() {
        match child.kind() {
            SECTION => {
                for keyword in child.children().filter_map(Keyword::cast) {
                    let key = keyword.key().to_string().to_uppercase();
                    let value = keyword.value().trim().to_string();
                    match file_keywords.get(&key) {
                        Some(Value::String(before)) if !before.is_empty() => {
                            let joined = format!("{before} {value}");
                            file_keywords.insert(key, Value::String(joined));
                        }
                        _ => {
                            file_keywords.insert(key, Value::String(value));
                        }
                    }
                }
                if let Some(drawer) = child.children().find_map(orgize::ast::PropertyDrawer::cast) {
                    root.set("properties", properties(&drawer));
                }
                let section = section(&child);
                if !section.children().is_empty() {
                    children.push(section);
                }
            }
            HEADLINE => children.push(headline(&child)),
            _ => {}
        }
    }
    if let Some(title) = file_keywords.get("TITLE").and_then(Value::as_str) {
        root.set("title", title.to_string());
    }
    root.set("keywords", Value::Object(file_keywords));
    root.set_children(children);
    root
}

/// `#+TODO: TODO NEXT | DONE` lines, read before the parse; the shortcuts
/// `(t!)` dropped, the last word done when there is no bar.
fn keywords(text: &str) -> (Vec<String>, Vec<String>) {
    let mut todo: Vec<String> = TODO.iter().map(|word| word.to_string()).collect();
    let mut done: Vec<String> = DONE.iter().map(|word| word.to_string()).collect();
    for line in text.lines() {
        let trimmed = line.trim_start();
        let Some(rest) = trimmed.strip_prefix("#+") else { continue };
        let Some((key, value)) = rest.split_once(':') else { continue };
        if !matches!(key.to_uppercase().as_str(), "TODO" | "SEQ_TODO" | "TYP_TODO") {
            continue;
        }
        let words: Vec<String> = value
            .split_whitespace()
            .map(|word| word.split('(').next().unwrap_or("").to_string())
            .filter(|word| !word.is_empty())
            .collect();
        let bar = words.iter().position(|word| word == "|");
        let (open, closed): (Vec<String>, Vec<String>) = match bar {
            Some(index) => (words[..index].to_vec(), words[index + 1..].to_vec()),
            None if words.len() > 1 => (words[..words.len() - 1].to_vec(), words[words.len() - 1..].to_vec()),
            None => (words.clone(), vec![]),
        };
        for word in open {
            if !todo.contains(&word) {
                todo.push(word);
            }
        }
        for word in closed {
            if !done.contains(&word) {
                done.push(word);
            }
        }
    }
    (todo, done)
}

fn range(node: &SyntaxNode) -> (usize, usize) {
    let range = node.text_range();
    (usize::from(range.start()), usize::from(range.end()))
}

fn section(node: &SyntaxNode) -> Node {
    let (begin, end) = range(node);
    let mut section = Node::new("section", begin, end);
    section.set_children(elements(node));
    section
}

/// The elements among a node's children, in order; planning and property
/// drawers are read onto their headline, keywords stay as elements.
fn elements(parent: &SyntaxNode) -> Vec<Node> {
    parent.children().filter_map(|child| element(&child)).collect()
}

fn element(node: &SyntaxNode) -> Option<Node> {
    let (begin, end) = range(node);
    let mut out = match node.kind() {
        PARAGRAPH => {
            let objects = objects(node);
            if objects.is_empty() {
                return None;
            }
            let mut paragraph = Node::new("paragraph", begin, end);
            paragraph.set("text", plain(&objects));
            paragraph.set_children(objects);
            paragraph
        }
        HEADLINE => headline(node),
        SECTION => section(node),
        LIST => {
            let list = List::cast(node.clone())?;
            let mut out = Node::new("plain-list", begin, end);
            out.set("listType", if list.is_ordered() { "ordered" } else if list.is_descriptive() { "descriptive" } else { "unordered" });
            out.set_children(node.children().filter_map(|child| ListItem::cast(child).map(|item| list_item(&item))).collect());
            out
        }
        ORG_TABLE => {
            let table = OrgTable::cast(node.clone())?;
            let mut out = Node::new("table", begin, end);
            out.set("tableType", "org");
            out.set("hasHeader", table.has_header());
            let formulas: Vec<Value> = table.tblfm().map(|token| Value::String(token.to_string())).collect();
            if !formulas.is_empty() {
                out.set("tblfm", Value::Array(formulas));
            }
            out.set_children(node.children().filter_map(|child| OrgTableRow::cast(child).map(|row| table_row(&row))).collect());
            out
        }
        TABLE_EL => {
            let mut out = Node::new("table", begin, end);
            out.set("tableType", "table.el");
            out.set("value", node.text().to_string());
            out
        }
        DRAWER => {
            let drawer = Drawer::cast(node.clone())?;
            let mut out = Node::new("drawer", begin, end);
            out.set("drawerName", drawer.name().to_string());
            out.set_children(node.children().filter(|child| child.kind() == DRAWER_CONTENT).flat_map(|content| elements(&content)).collect());
            out
        }
        PROPERTY_DRAWER | PLANNING => return None,
        KEYWORD => {
            let keyword = Keyword::cast(node.clone())?;
            let mut out = Node::new("keyword", begin, end);
            out.set("key", keyword.key().to_string().to_uppercase());
            out.set("value", keyword.value().trim().to_string());
            out
        }
        BABEL_CALL => {
            let mut out = Node::new("babel-call", begin, end);
            out.set("value", node.text().to_string().trim().to_string());
            out
        }
        CLOCK => {
            let clock = Clock::cast(node.clone())?;
            let mut out = Node::new("clock", begin, end);
            out.set("status", if clock.is_running() { "running" } else { "closed" });
            out.set_if("duration", clock.duration().map(|token| token.to_string()));
            if let Some(stamp) = clock.value() {
                out.set("value", timestamp(&stamp).into_value());
            }
            out
        }
        FN_DEF => {
            let mut out = Node::new("footnote-definition", begin, end);
            let raw = node.text().to_string();
            out.set_if("label", raw.strip_prefix("[fn:").and_then(|rest| rest.split(']').next()).map(str::to_string));
            out.set_children(node.children().filter_map(|child| element(&child)).collect());
            if out.children().is_empty() {
                let after_label = node
                    .children_with_tokens()
                    .skip_while(|child| child.kind() != R_BRACKET)
                    .skip(1)
                    .collect::<Vec<_>>();
                let objects = trim_text(objects_of(after_label));
                out.set("text", plain(&objects));
                out.set_children(objects);
            }
            out
        }
        COMMENT => {
            let comment = Comment::cast(node.clone())?;
            let mut out = Node::new("comment", begin, end);
            out.set("value", comment.value().trim_end_matches(['\n', '\r']).to_string());
            out
        }
        RULE => Node::new("horizontal-rule", begin, end),
        FIXED_WIDTH => {
            let fixed = FixedWidth::cast(node.clone())?;
            let mut out = Node::new("fixed-width", begin, end);
            out.set("value", fixed.value().trim_end_matches(['\n', '\r']).to_string());
            out
        }
        DYN_BLOCK => {
            let mut out = Node::new("dynamic-block", begin, end);
            let first = node.text().to_string().lines().next().unwrap_or("").trim().to_string();
            let rest = first.get(first.to_uppercase().find("#+BEGIN:").map(|at| at + 8).unwrap_or(first.len())..).unwrap_or("").trim();
            let (name, arguments) = rest.split_once(' ').map(|(a, b)| (a.to_string(), b.trim().to_string())).unwrap_or((rest.to_string(), String::new()));
            out.set("blockName", name);
            if !arguments.is_empty() {
                out.set("arguments", arguments);
            }
            out.set_children(contents(node));
            out
        }
        SOURCE_BLOCK => {
            let block = SourceBlock::cast(node.clone())?;
            let mut out = Node::new("src-block", begin, end);
            out.set_if("language", block.language().map(|token| token.to_string()));
            out.set_if("parameters", block.parameters().map(|token| token.to_string().trim().to_string()));
            out.set_if("switches", block.switches().map(|token| token.to_string().trim().to_string()));
            out.set("value", block.value());
            out
        }
        EXAMPLE_BLOCK | COMMENT_BLOCK => {
            let mut out = Node::new(if node.kind() == EXAMPLE_BLOCK { "example-block" } else { "comment-block" }, begin, end);
            out.set("value", block_value(node));
            out
        }
        EXPORT_BLOCK => {
            let block = ExportBlock::cast(node.clone())?;
            let mut out = Node::new("export-block", begin, end);
            out.set_if("backend", block.ty().map(|token| token.to_string().to_lowercase()));
            out.set("value", block.value());
            out
        }
        QUOTE_BLOCK | CENTER_BLOCK | VERSE_BLOCK | SPECIAL_BLOCK => {
            let kind = match node.kind() {
                QUOTE_BLOCK => "quote-block",
                CENTER_BLOCK => "center-block",
                VERSE_BLOCK => "verse-block",
                _ => "special-block",
            };
            let mut out = Node::new(kind, begin, end);
            if node.kind() == SPECIAL_BLOCK {
                let first = node.text().to_string().lines().next().unwrap_or("").trim().to_string();
                let name = first.get(first.to_uppercase().find("#+BEGIN_").map(|at| at + 8).unwrap_or(first.len())..).unwrap_or("");
                out.set("blockType", name.split_whitespace().next().unwrap_or("").to_string());
                let _ = SpecialBlock::cast(node.clone());
            }
            out.set_children(contents(node));
            out
        }
        LATEX_ENVIRONMENT => {
            let mut out = Node::new("latex-environment", begin, end);
            out.set("value", node.text().to_string());
            out
        }
        _ => return None,
    };
    affiliated(node, &mut out);
    Some(out)
}

/// `#+NAME:`, `#+CAPTION:` and the like written above an element, as its
/// own properties.
fn affiliated(node: &SyntaxNode, out: &mut Node) {
    for keyword in node.children().filter_map(AffiliatedKeyword::cast) {
        let raw = keyword.syntax().text().to_string();
        let trimmed = raw.trim();
        let Some(rest) = trimmed.strip_prefix("#+") else { continue };
        let Some((key, value)) = rest.split_once(':') else { continue };
        let key = key.split('[').next().unwrap_or(key).to_lowercase();
        if matches!(key.as_str(), "name" | "caption" | "header" | "plot" | "results") || key.starts_with("attr_") {
            out.set(&key, value.trim().to_string());
        }
    }
}

fn block_value(node: &SyntaxNode) -> String {
    node.children()
        .filter(|child| child.kind() == BLOCK_CONTENT)
        .map(|content| content.text().to_string())
        .collect::<Vec<_>>()
        .join("")
}

/// The contents of a block: elements when it holds any, else its objects.
fn contents(node: &SyntaxNode) -> Vec<Node> {
    let content: Vec<SyntaxNode> = node.children().filter(|child| child.kind() == BLOCK_CONTENT || child.kind() == DRAWER_CONTENT).collect();
    let mut found = Vec::new();
    for content in content {
        let elements = elements(&content);
        if elements.is_empty() {
            let objects = objects(&content);
            if !objects.is_empty() {
                let (begin, end) = range(&content);
                let mut paragraph = Node::new("paragraph", begin, end);
                paragraph.set("text", plain(&objects));
                paragraph.set_children(objects);
                found.push(paragraph);
            }
        } else {
            found.extend(elements);
        }
    }
    found
}

fn headline(node: &SyntaxNode) -> Node {
    let (begin, end) = range(node);
    let mut out = Node::new("headline", begin, end);
    let Some(headline) = Headline::cast(node.clone()) else { return out };
    out.set("level", headline.level());
    let mut title: Vec<Node> = trim_text(headline.title().filter_map(object).collect());
    if let Some(last) = title.last_mut() {
        if last.kind() == "plain-text" {
            let value = last.get("value").as_str().unwrap_or("").to_string();
            let trimmed = value.trim_end();
            let end = last.end() - (value.len() - trimmed.len());
            last.set("value", trimmed.to_string());
            last.set("end", end);
        }
    }
    if headline.is_commented() {
        if let Some(first) = title.first_mut() {
            let value = first.get("value").as_str().unwrap_or("").to_string();
            if let Some(rest) = value.strip_prefix("COMMENT") {
                let rest = rest.trim_start();
                let begin = first.begin() + (value.len() - rest.len());
                first.set("value", rest.to_string());
                first.set("begin", begin);
            }
        }
        title.retain(|node| node.kind() != "plain-text" || !node.get("value").as_str().unwrap_or("").is_empty());
    }
    out.set("title", plain(&title));
    out.set_objects(title);
    out.set_if("todoKeyword", headline.todo_keyword().map(|token| token.to_string()));
    out.set_if("todoType", headline.todo_type().map(|kind| if kind == TodoType::Done { "done" } else { "todo" }));
    out.set_if("priority", headline.priority().map(|token| token.to_string()));
    let tags: Vec<Value> = headline.tags().map(|token| Value::String(token.to_string())).collect();
    out.set("tags", Value::Array(tags));
    if headline.is_archived() {
        out.set("archived", true);
    }
    if headline.is_commented() {
        out.set("commented", true);
    }
    if let Some(stamp) = headline.scheduled() {
        out.set("scheduled", timestamp(&stamp).into_value());
    }
    if let Some(stamp) = headline.deadline() {
        out.set("deadline", timestamp(&stamp).into_value());
    }
    if let Some(stamp) = headline.closed() {
        out.set("closed", timestamp(&stamp).into_value());
    }
    if let Some(drawer) = headline.properties() {
        out.set("properties", properties(&drawer));
    }
    let mut children = Vec::new();
    for child in node.children() {
        match child.kind() {
            SECTION => {
                let section = section(&child);
                if !section.children().is_empty() {
                    children.push(section);
                }
            }
            HEADLINE => children.push(headline_node(&child)),
            _ => {}
        }
    }
    out.set_children(children);
    out
}

fn headline_node(node: &SyntaxNode) -> Node {
    headline(node)
}

fn properties(drawer: &orgize::ast::PropertyDrawer) -> Value {
    let mut map = Map::new();
    for (key, value) in drawer.iter() {
        map.insert(key.to_string(), Value::String(value.to_string()));
    }
    Value::Object(map)
}

fn list_item(item: &ListItem) -> Node {
    let node = item.syntax();
    let (begin, end) = range(node);
    let mut out = Node::new("item", begin, end);
    out.set("bullet", item.bullet().to_string().trim().to_string());
    out.set("indent", item.indent());
    if let Some(check) = item.checkbox() {
        let raw = check.to_string();
        out.set("checkbox", match raw.trim_matches(['[', ']']) {
            "X" | "x" => "on",
            "-" => "trans",
            _ => "off",
        });
        let token = check.syntax();
        let (start, stop) = (usize::from(token.text_range().start()), usize::from(token.text_range().end()));
        let bracketed = raw.starts_with('[');
        out.set("checkboxBegin", if bracketed { start } else { start.saturating_sub(1) });
        out.set("checkboxEnd", if bracketed { stop } else { stop + 1 });
    }
    out.set_if("counter", item.counter().map(|token| token.to_string()));
    let tag: Vec<Node> = item.tag().filter_map(object).collect();
    if !tag.is_empty() {
        out.set("tag", plain(&tag));
    }
    let mut children = Vec::new();
    let mut text = Vec::new();
    let mut content_begin = None;
    let mut content_end = None;
    for content in node.children().filter(|child| child.kind() == LIST_ITEM_CONTENT) {
        let (start, _) = range(&content);
        content_begin.get_or_insert(start);
        for child in content.children() {
            if let Some(element) = element(&child) {
                if element.kind() == "paragraph" && children.is_empty() {
                    text.push(element.get("text").as_str().unwrap_or("").to_string());
                    content_end = Some(trimmed_end(&child));
                }
                children.push(element);
            }
        }
    }
    if content_begin.is_none() {
        content_begin = Some(end);
    }
    let mut text = text.join(" ");
    if out.get("tag").is_null() {
        if let Some((tag, rest)) = text.split_once(" :: ") {
            if !tag.is_empty() && !tag.contains('\n') {
                out.set("tag", tag.to_string());
                text = rest.to_string();
            }
        }
    }
    out.set("text", text);
    out.set("contentBegin", content_begin.unwrap_or(end));
    out.set("contentEnd", content_end.unwrap_or(content_begin.unwrap_or(end)));
    out.set_children(children);
    out
}

/// Where a node's text ends once trailing blank lines and spaces are left out.
fn trimmed_end(node: &SyntaxNode) -> usize {
    let text = node.text().to_string();
    let trimmed = text.trim_end();
    usize::from(node.text_range().start()) + trimmed.len()
}

fn table_row(row: &OrgTableRow) -> Node {
    let node = row.syntax();
    let (begin, end) = range(node);
    let mut out = Node::new("table-row", begin, end);
    out.set("rowType", if row.is_rule() { "rule" } else { "standard" });
    if row.is_standard() {
        out.set_children(
            node.children()
                .filter(|child| child.kind() == ORG_TABLE_CELL)
                .map(|cell| {
                    let (begin, end) = range(&cell);
                    let mut out = Node::new("table-cell", begin, end);
                    let objects = objects(&cell);
                    out.set("text", plain(&objects));
                    out.set_children(objects);
                    out
                })
                .collect(),
        );
    }
    out
}

/// The objects of a node that holds text: its tokens as plain text, its
/// child nodes as the objects they are.
fn objects(parent: &SyntaxNode) -> Vec<Node> {
    trim_text(objects_of(parent.children_with_tokens().collect()))
}

fn objects_of(children: Vec<SyntaxElement>) -> Vec<Node> {
    let mut found: Vec<Node> = Vec::new();
    for child in children {
        match child {
            NodeOrToken::Token(token) => {
                if matches!(token.kind(), AFFILIATED_KEYWORD | BLANK_LINE) {
                    continue;
                }
                push_text(&mut found, usize::from(token.text_range().start()), usize::from(token.text_range().end()), token.text());
            }
            NodeOrToken::Node(node) => {
                if node.kind() == AFFILIATED_KEYWORD {
                    continue;
                }
                if let Some(object) = object(NodeOrToken::Node(node.clone())) {
                    found.push(object);
                } else {
                    let (begin, end) = range(&node);
                    push_text(&mut found, begin, end, &node.text().to_string());
                }
            }
        }
    }
    found
}

fn push_text(found: &mut Vec<Node>, begin: usize, end: usize, text: &str) {
    if text.is_empty() {
        return;
    }
    if let Some(last) = found.last_mut() {
        if last.kind() == "plain-text" && last.end() == begin {
            let value = format!("{}{}", last.get("value").as_str().unwrap_or(""), text);
            last.set("value", value);
            last.set("end", end);
            return;
        }
    }
    let mut node = Node::new("plain-text", begin, end);
    node.set("value", text.to_string());
    found.push(node);
}

/// Trailing newlines of a paragraph's last text are not part of what it says.
fn trim_text(mut found: Vec<Node>) -> Vec<Node> {
    if let Some(last) = found.last_mut() {
        if last.kind() == "plain-text" {
            let value = last.get("value").as_str().unwrap_or("").to_string();
            let trimmed = value.trim_end_matches(['\n', '\r']);
            if trimmed.len() != value.len() {
                let end = last.end() - (value.len() - trimmed.len());
                last.set("value", trimmed.to_string());
                last.set("end", end);
            }
            if trimmed.is_empty() {
                found.pop();
            }
        }
    }
    found
}

const MARKERS: [SyntaxKind; 10] = [STAR, SLASH, UNDERSCORE, PLUS, EQUAL, TILDE, CARET, L_CURLY, L_ANGLE3, R_ANGLE3];

/// Inner objects of a marked-up span: the markers around it left out.
fn inner_objects(node: &SyntaxNode) -> Vec<Node> {
    let mut found: Vec<Node> = Vec::new();
    let children: Vec<SyntaxElement> = node.children_with_tokens().collect();
    let count = children.len();
    for (index, child) in children.into_iter().enumerate() {
        match child {
            NodeOrToken::Token(token) => {
                if (index == 0 || index == count - 1) && (MARKERS.contains(&token.kind()) || token.kind() == R_CURLY || token.kind() == UNDERSCORE) {
                    continue;
                }
                if matches!(token.kind(), L_CURLY | R_CURLY) && (index <= 1 || index >= count.saturating_sub(2)) {
                    continue;
                }
                push_text(&mut found, usize::from(token.text_range().start()), usize::from(token.text_range().end()), token.text());
            }
            NodeOrToken::Node(inner) => {
                if let Some(object) = object(NodeOrToken::Node(inner.clone())) {
                    found.push(object);
                } else {
                    let (begin, end) = range(&inner);
                    push_text(&mut found, begin, end, &inner.text().to_string());
                }
            }
        }
    }
    found
}

fn inner_value(node: &SyntaxNode) -> String {
    let text = node.text().to_string();
    let mut chars = text.chars();
    chars.next();
    chars.next_back();
    chars.as_str().to_string()
}

fn object(element: SyntaxElement) -> Option<Node> {
    let node = match element {
        NodeOrToken::Node(node) => node,
        NodeOrToken::Token(token) => {
            let mut out = Node::new("plain-text", usize::from(token.text_range().start()), usize::from(token.text_range().end()));
            out.set("value", token.text().to_string());
            return Some(out);
        }
    };
    let (begin, end) = range(&node);
    let mut out = match node.kind() {
        BOLD | ITALIC | UNDERLINE | STRIKE | SUPERSCRIPT | SUBSCRIPT => {
            let kind = match node.kind() {
                BOLD => "bold",
                ITALIC => "italic",
                UNDERLINE => "underline",
                STRIKE => "strike-through",
                SUPERSCRIPT => "superscript",
                _ => "subscript",
            };
            let mut out = Node::new(kind, begin, end);
            out.set_children(inner_objects(&node));
            out
        }
        CODE | VERBATIM => {
            let mut out = Node::new(if node.kind() == CODE { "code" } else { "verbatim" }, begin, end);
            out.set("value", inner_value(&node));
            out
        }
        LINK => {
            let link = Link::cast(node.clone())?;
            let mut out = Node::new("link", begin, end);
            let raw = link.path().to_string();
            let (path, search) = match raw.split_once("::") {
                Some((path, search)) => (path.to_string(), Some(search.to_string())),
                None => (raw.clone(), None),
            };
            let (kind, rest) = match path.split_once(':') {
                Some((scheme, rest)) if !scheme.is_empty() && scheme.chars().all(|c| c.is_ascii_alphanumeric() || c == '+' || c == '-' || c == '.') => {
                    (scheme.to_lowercase(), rest.to_string())
                }
                _ => ("fuzzy".to_string(), path.clone()),
            };
            out.set("linkType", kind);
            out.set("path", rest);
            out.set("rawLink", raw);
            out.set_if("searchOption", search);
            if link.is_image() {
                out.set("isImage", true);
            }
            let description: Vec<Node> = if link.has_description() { link.description().filter_map(object).collect() } else { vec![] };
            if !description.is_empty() {
                out.set("text", plain(&description));
                out.set_children(description);
            }
            out
        }
        TIMESTAMP_ACTIVE | TIMESTAMP_INACTIVE | TIMESTAMP_DIARY => timestamp(&Timestamp::cast(node.clone())?),
        COOKIE => {
            let mut out = Node::new("statistics-cookie", begin, end);
            out.set("value", node.text().to_string());
            out
        }
        FN_REF => {
            let mut out = Node::new("footnote-reference", begin, end);
            let raw = node.text().to_string();
            let inside = raw.strip_prefix("[fn:").and_then(|rest| rest.strip_suffix(']')).unwrap_or("");
            let (label, definition) = inside.split_once(':').map(|(a, b)| (a.to_string(), Some(b.to_string()))).unwrap_or((inside.to_string(), None));
            if !label.is_empty() {
                out.set("label", label);
            }
            out.set_if("definition", definition);
            out
        }
        ENTITY => {
            let entity = Entity::cast(node.clone())?;
            let mut out = Node::new("entity", begin, end);
            out.set("name", entity.name().to_string());
            out.set("utf8", entity.utf8().to_string());
            out
        }
        LATEX_FRAGMENT => {
            let mut out = Node::new("latex-fragment", begin, end);
            out.set("value", node.text().to_string());
            out
        }
        LINE_BREAK => Node::new("line-break", begin, end),
        TARGET => {
            let mut out = Node::new("target", begin, end);
            out.set("value", node.text().to_string().trim_start_matches('<').trim_end_matches('>').to_string());
            out
        }
        RADIO_TARGET => {
            let mut out = Node::new("radio-target", begin, end);
            out.set_children(inner_objects(&node));
            out
        }
        MACROS => {
            let macros = Macros::cast(node.clone())?;
            let mut out = Node::new("macro", begin, end);
            out.set("key", macros.key().to_string());
            out.set_if("args", macros.args().map(|token| token.to_string()));
            out
        }
        SNIPPET => {
            let snippet = Snippet::cast(node.clone())?;
            let mut out = Node::new("export-snippet", begin, end);
            out.set("backend", snippet.backend().to_string());
            out.set("value", snippet.value().to_string());
            out
        }
        INLINE_SRC => {
            let src = InlineSrc::cast(node.clone())?;
            let mut out = Node::new("inline-src-block", begin, end);
            out.set("language", src.language().to_string());
            out.set_if("parameters", src.parameters().map(|token| token.to_string()));
            out.set("value", src.value().to_string());
            out
        }
        INLINE_CALL => {
            let call = InlineCall::cast(node.clone())?;
            let mut out = Node::new("inline-babel-call", begin, end);
            out.set("arguments", call.arguments().to_string());
            out.set("value", node.text().to_string());
            out
        }
        _ => return None,
    };
    let _ = &mut out;
    Some(out)
}

fn timestamp(stamp: &Timestamp) -> Node {
    let node = stamp.syntax();
    let (begin, end) = range(node);
    let mut out = Node::new("timestamp", begin, end);
    let base = if stamp.is_diary() { "diary" } else if stamp.is_active() { "active" } else { "inactive" };
    out.set("timestampType", if stamp.is_range() && !stamp.is_diary() { format!("{base}-range") } else { base.to_string() });
    out.set("rawValue", node.text().to_string());
    let mut years = Vec::new();
    let mut months = Vec::new();
    let mut days = Vec::new();
    let mut hours = Vec::new();
    let mut minutes = Vec::new();
    for child in node.children_with_tokens() {
        if let NodeOrToken::Token(token) = child {
            let text = token.text().to_string();
            match token.kind() {
                TIMESTAMP_YEAR => years.push(text),
                TIMESTAMP_MONTH => months.push(text),
                TIMESTAMP_DAY => days.push(text),
                TIMESTAMP_HOUR => hours.push(text),
                TIMESTAMP_MINUTE => minutes.push(text),
                _ => {}
            }
        }
    }
    let date = |index: usize| -> Option<String> { Some(format!("{}-{:0>2}-{:0>2}", years.get(index)?, months.get(index)?, days.get(index)?)) };
    let time = |index: usize| -> Option<String> { Some(format!("{:0>2}:{:0>2}", hours.get(index)?, minutes.get(index)?)) };
    let moment = |date: Option<String>, time: Option<String>| -> Option<String> {
        let date = date?;
        Some(match time {
            Some(time) => format!("{date}T{time}"),
            None => date,
        })
    };
    out.set_if("start", moment(date(0), time(0)));
    if years.len() > 1 || hours.len() > 1 {
        out.set_if("end", moment(date(1).or_else(|| date(0)), time(if years.len() > 1 { 1 } else { 1 })));
        if !out.get("timestampType").as_str().unwrap_or("").ends_with("-range") {
            let kind = format!("{}-range", out.get("timestampType").as_str().unwrap_or("active"));
            out.set("timestampType", kind);
        }
    }
    if let (Some(kind), Some(value), Some(unit)) = (stamp.repeater_type(), stamp.repeater_value(), stamp.repeater_unit()) {
        out.set("repeater", json!({"type": format!("{kind:?}").to_lowercase(), "value": value, "unit": format!("{unit:?}").to_lowercase()}));
    }
    if let (Some(kind), Some(value), Some(unit)) = (stamp.warning_type(), stamp.warning_value(), stamp.warning_unit()) {
        out.set("warning", json!({"type": format!("{kind:?}").to_lowercase(), "value": value, "unit": format!("{unit:?}").to_lowercase()}));
    }
    out
}

