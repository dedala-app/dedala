// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

use orgize::rowan::ast::AstNode;
fn main() {
    let text = std::env::args().nth(1).unwrap_or_default();
    let org = orgize::Org::parse(&text);
    println!("{:#?}", org.document().syntax());
}
