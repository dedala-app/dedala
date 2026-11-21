// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! The plugin's WebAssembly module: strings go in through memory the host
//! asks for with `dedala_alloc`, results come back as one word holding a
//! pointer and a length, which the host reads and gives back with
//! `dedala_free`.

use std::time::Duration;

#[no_mangle]
pub extern "C" fn dedala_alloc(length: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(length.max(1));
    let pointer = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    pointer
}

/// # Safety
/// `pointer` and `length` are what `dedala_alloc` was asked for, or a result.
#[no_mangle]
pub unsafe extern "C" fn dedala_free(pointer: *mut u8, length: usize) {
    drop(Vec::from_raw_parts(pointer, 0, length.max(1)));
}

fn text(pointer: *const u8, length: usize) -> String {
    String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(pointer, length) }).into_owned()
}

fn give(bytes: Vec<u8>) -> u64 {
    let pointer = dedala_alloc(bytes.len());
    unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), pointer, bytes.len()) };
    ((pointer as u64) << 32) | bytes.len() as u64
}

/// The tree of a text as JSON.
#[no_mangle]
pub extern "C" fn dedala_org_parse(text_pointer: *const u8, text_length: usize, format_pointer: *const u8, format_length: usize) -> u64 {
    let tree = crate::parse(&text(text_pointer, text_length), &text(format_pointer, format_length));
    give(serde_json::to_vec(tree.value()).unwrap_or_else(|_| b"{}".to_vec()))
}

/// A text's boundaries of one kind (0 line, 1 word, 2 grapheme) in
/// characters, as little-endian u32.
#[no_mangle]
pub extern "C" fn dedala_breaks(kind: u32, pointer: *const u8, length: usize) -> u64 {
    let breaks = crate::segment::breaks(kind, &text(pointer, length));
    give(breaks.iter().flat_map(|point| point.to_le_bytes()).collect())
}

#[no_mangle]
pub extern "C" fn dedala_is_emoji(code_point: u32) -> u32 {
    crate::segment::is_emoji(code_point) as u32
}

/// A script run: `{"output", "error"}` as JSON.
#[no_mangle]
pub extern "C" fn dedala_run_script(pointer: *const u8, length: usize, milliseconds: u32) -> u64 {
    let ran = crate::script::run(&text(pointer, length), Duration::from_millis(milliseconds as u64));
    give(serde_json::to_vec(&serde_json::json!({"output": ran.output, "error": ran.error})).unwrap_or_default())
}
