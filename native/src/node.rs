// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

use serde_json::{json, Map, Value};

/// One node of the tree: an object with `type`, its properties, `begin` and
/// `end`, and `children` when it holds other nodes (`objects` for a
/// headline's title, drawn beside its `children`).
#[derive(Clone, Debug, PartialEq)]
pub struct Node(Value);

impl Node {
    pub fn new(kind: &str, begin: usize, end: usize) -> Node {
        Node(json!({"type": kind, "begin": begin, "end": end}))
    }

    pub fn kind(&self) -> &str {
        self.0["type"].as_str().unwrap_or("")
    }

    pub fn value(&self) -> &Value {
        &self.0
    }

    pub fn into_value(self) -> Value {
        self.0
    }

    pub fn get(&self, key: &str) -> &Value {
        &self.0[key]
    }

    pub fn set(&mut self, key: &str, value: impl Into<Value>) -> &mut Node {
        let value = value.into();
        if !value.is_null() {
            self.map().insert(key.to_string(), value);
        }
        self
    }

    pub fn set_if(&mut self, key: &str, value: Option<impl Into<Value>>) -> &mut Node {
        if let Some(value) = value {
            self.set(key, value);
        }
        self
    }

    pub fn set_children(&mut self, children: Vec<Node>) -> &mut Node {
        self.map().insert("children".to_string(), Value::Array(children.into_iter().map(Node::into_value).collect()));
        self
    }

    pub fn set_objects(&mut self, objects: Vec<Node>) -> &mut Node {
        self.map().insert("objects".to_string(), Value::Array(objects.into_iter().map(Node::into_value).collect()));
        self
    }

    pub fn children(&self) -> Vec<Node> {
        Self::nodes(&self.0["children"])
    }

    pub fn objects(&self) -> Vec<Node> {
        Self::nodes(&self.0["objects"])
    }

    fn nodes(value: &Value) -> Vec<Node> {
        value.as_array().map(|items| items.iter().cloned().map(Node).collect()).unwrap_or_default()
    }

    pub fn begin(&self) -> usize {
        self.0["begin"].as_u64().unwrap_or(0) as usize
    }

    pub fn end(&self) -> usize {
        self.0["end"].as_u64().unwrap_or(0) as usize
    }

    fn map(&mut self) -> &mut Map<String, Value> {
        self.0.as_object_mut().expect("a node is an object")
    }
}

impl From<Node> for Value {
    fn from(node: Node) -> Value {
        node.0
    }
}
