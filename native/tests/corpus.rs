// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Every file of `corpus/` parses to the tree beside it (`<name>.json`).
//! `UPDATE_CORPUS=1 cargo test` writes the trees anew after a deliberate
//! change; the diff is then reviewed like any other.

use std::fs;
use std::path::Path;

#[test]
fn the_corpus_parses_as_recorded() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("corpus");
    let update = std::env::var("UPDATE_CORPUS").is_ok();
    let mut checked = 0;
    let mut wrong = Vec::new();
    let mut entries: Vec<_> = fs::read_dir(&root).expect("a corpus directory").flatten().map(|entry| entry.path()).collect();
    entries.sort();
    for path in entries {
        let Some(extension) = path.extension().and_then(|e| e.to_str()) else { continue };
        let format = match extension {
            "org" => "org",
            "md" => "markdown",
            _ => continue,
        };
        let text = fs::read_to_string(&path).expect("a readable fixture");
        let tree = dedala_native::parse(&text, format);
        let json = serde_json::to_string_pretty(tree.value()).expect("a tree") + "\n";
        let expected = path.with_extension("json");
        if update || !expected.exists() {
            fs::write(&expected, &json).expect("the tree written");
        } else if fs::read_to_string(&expected).expect("a recorded tree") != json {
            wrong.push(path.display().to_string());
        }
        checked += 1;
    }
    assert!(checked > 0, "no fixtures in {}", root.display());
    assert!(wrong.is_empty(), "trees changed for {wrong:?}; run with UPDATE_CORPUS=1 and review the diff");
}

#[test]
fn a_tree_reads_back_through_the_c_interface() {
    use std::ffi::{CStr, CString};
    let text = CString::new("* TODO Call [[denote:20260107T170819][Anna]] :work:\nSCHEDULED: <2026-05-12 Tue 09:30>\n- [ ] prepare\n  the slides\n- [X] book a room\n").unwrap();
    let format = CString::new("org").unwrap();
    let pointer = dedala_native::hermes_org_parse(text.as_ptr(), format.as_ptr());
    let json = unsafe { CStr::from_ptr(pointer) }.to_str().unwrap().to_string();
    dedala_native::hermes_org_free(pointer);
    let tree: serde_json::Value = serde_json::from_str(&json).unwrap();
    let headline = &tree["children"][0];
    assert_eq!(headline["type"], "headline");
    assert_eq!(headline["todoKeyword"], "TODO");
    assert_eq!(headline["title"], "Call Anna");
    assert_eq!(headline["tags"][0], "work");
    assert_eq!(headline["scheduled"]["start"], "2026-05-12T09:30");
    let items = dedala_native::select(&dedala_native::parse(text.to_str().unwrap(), "org"), "item");
    assert_eq!(items.len(), 2);
    assert_eq!(items[0].get("text"), "prepare the slides");
    assert_eq!(items[0].get("checkbox"), "off");
    assert_eq!(items[1].get("checkbox"), "on");
    let link = dedala_native::select(&dedala_native::parse(text.to_str().unwrap(), "org"), "link");
    assert_eq!(link[0].get("linkType"), "denote");
    assert_eq!(link[0].get("path"), "20260107T170819");
}
