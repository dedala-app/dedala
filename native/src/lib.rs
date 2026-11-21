// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Org and Markdown read into one tree, in the vocabulary of Org's own
//! element API (org-element): every node is `{"type", …properties, "children"}`
//! with its byte range in the text as `begin`/`end`, and `text`, its contents
//! as plain words. The phone and the plugin call `hermes_org_parse` and read
//! the JSON; nothing else crosses.

mod markdown;
mod node;
mod org;
#[cfg(feature = "plugin")]
pub mod script;
#[cfg(feature = "plugin")]
pub mod segment;
mod text;
#[cfg(all(feature = "plugin", target_arch = "wasm32"))]
mod wasm;

use std::ffi::{c_char, CStr, CString};

pub use node::Node;

/// The tree of a text: `format` is "org" or "markdown"; anything else is
/// told apart from the text (`#+`, `*` headlines mean Org).
pub fn parse(text: &str, format: &str) -> Node {
    match format {
        "org" => org::parse(text),
        "markdown" | "md" => markdown::parse(text),
        _ if looks_like_org(text) => org::parse(text),
        _ => markdown::parse(text),
    }
}

/// The nodes of one type anywhere in the tree, in document order.
pub fn select(tree: &Node, kind: &str) -> Vec<Node> {
    let mut found = Vec::new();
    fn walk(node: &Node, kind: &str, found: &mut Vec<Node>) {
        if node.kind() == kind {
            found.push(node.clone());
        }
        for child in node.children() {
            walk(&child, kind, found);
        }
        for child in node.objects() {
            walk(&child, kind, found);
        }
    }
    walk(tree, kind, &mut found);
    found
}

fn looks_like_org(text: &str) -> bool {
    text.lines().take(50).any(|line| line.starts_with("#+") || (line.starts_with('*') && line.trim_start_matches('*').starts_with(' ')))
}

/// `hermes_org_parse(text, format)`: the tree as JSON, to be given back with
/// `hermes_org_free`. A null text parses as empty; invalid UTF-8 is read with
/// replacement characters.
#[no_mangle]
pub extern "C" fn hermes_org_parse(text: *const c_char, format: *const c_char) -> *mut c_char {
    let text = if text.is_null() { String::new() } else { unsafe { CStr::from_ptr(text) }.to_string_lossy().into_owned() };
    let format = if format.is_null() { String::new() } else { unsafe { CStr::from_ptr(format) }.to_string_lossy().into_owned() };
    let tree = parse(&text, &format);
    let json = serde_json::to_string(tree.value()).unwrap_or_else(|_| "{}".to_string());
    CString::new(json.replace('\0', "")).map(CString::into_raw).unwrap_or(std::ptr::null_mut())
}

#[no_mangle]
pub extern "C" fn hermes_org_free(text: *mut c_char) {
    if !text.is_null() {
        unsafe { drop(CString::from_raw(text)) };
    }
}
