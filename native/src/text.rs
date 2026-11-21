// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

use crate::node::Node;

/// The words of a node's contents, as read aloud: markup dropped, a link its
/// description (or its path), a timestamp as written, an entity its
/// character, newlines inside the text as spaces.
pub fn plain(nodes: &[Node]) -> String {
    let mut out = String::new();
    for node in nodes {
        write(node, &mut out);
    }
    collapse(&out)
}

fn write(node: &Node, out: &mut String) {
    match node.kind() {
        "plain-text" | "code" | "verbatim" | "statistics-cookie" | "latex-fragment" | "target" | "inline-src-block" => {
            out.push_str(node.get("value").as_str().unwrap_or(""));
        }
        "timestamp" => out.push_str(node.get("rawValue").as_str().unwrap_or("")),
        "entity" => out.push_str(node.get("utf8").as_str().unwrap_or("")),
        "line-break" => out.push('\n'),
        "link" => {
            let children = node.children();
            if children.is_empty() {
                out.push_str(node.get("path").as_str().unwrap_or(""));
            } else {
                for child in &children {
                    write(child, out);
                }
            }
        }
        "footnote-reference" | "macro" | "export-snippet" | "inline-babel-call" => {}
        _ => {
            for child in &node.children() {
                write(child, out);
            }
        }
    }
}

/// Newlines (hard wrapping) become spaces and runs of spaces one space.
pub fn collapse(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut space = false;
    for character in text.chars() {
        if character == '\n' || character == '\r' || character == ' ' || character == '\t' {
            space = true;
        } else {
            if space && !out.is_empty() {
                out.push(' ');
            }
            space = false;
            out.push(character);
        }
    }
    out
}
