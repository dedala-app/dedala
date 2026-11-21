// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Line, word and grapheme boundaries as the phone finds them. The phone's text
//! system uses ICU; this is ICU4X, which agrees with it once two of ICU's line
//! rules are added (`icu_rules`): measured on 5,356 texts, only minified
//! script differs. Boundaries are counted in characters (code points), the
//! way the twin indexes its strings.

use std::sync::OnceLock;

use icu_properties::props::Emoji;
use icu_properties::{CodePointSetData, CodePointSetDataBorrowed};
use icu_segmenter::options::{LineBreakOptions, LineBreakStrictness, WordBreakInvariantOptions};
use icu_segmenter::{GraphemeClusterSegmenter, GraphemeClusterSegmenterBorrowed, LineSegmenter, LineSegmenterBorrowed,
                    WordSegmenter, WordSegmenterBorrowed};

pub const LINE: u32 = 0;
pub const WORD: u32 = 1;
pub const GRAPHEME: u32 = 2;

fn line() -> &'static LineSegmenterBorrowed<'static> {
    static SEGMENTER: OnceLock<LineSegmenterBorrowed<'static>> = OnceLock::new();
    SEGMENTER.get_or_init(|| {
        let mut options = LineBreakOptions::default();
        options.strictness = Some(LineBreakStrictness::Normal);
        LineSegmenter::new_for_non_complex_scripts(options)
    })
}

fn word() -> &'static WordSegmenterBorrowed<'static> {
    static SEGMENTER: OnceLock<WordSegmenterBorrowed<'static>> = OnceLock::new();
    SEGMENTER.get_or_init(|| WordSegmenter::new_for_non_complex_scripts(WordBreakInvariantOptions::default()))
}

fn grapheme() -> &'static GraphemeClusterSegmenterBorrowed<'static> {
    static SEGMENTER: OnceLock<GraphemeClusterSegmenterBorrowed<'static>> = OnceLock::new();
    SEGMENTER.get_or_init(GraphemeClusterSegmenter::new)
}

/// The boundaries of a text of one kind, in characters, the start included.
pub fn breaks(kind: u32, text: &str) -> Vec<u32> {
    let bytes: Vec<usize> = match kind {
        LINE => line().segment_str(text).collect(),
        WORD => word().segment_str(text).collect(),
        _ => grapheme().segment_str(text).collect(),
    };
    let mut characters = Vec::with_capacity(bytes.len());
    let mut wanted = bytes.iter().peekable();
    for (index, (offset, _)) in text.char_indices().chain(std::iter::once((text.len(), ' '))).enumerate() {
        while wanted.peek().is_some_and(|&&b| b < offset) {
            wanted.next();
        }
        if wanted.peek() == Some(&&offset) {
            characters.push(index as u32);
            wanted.next();
        }
    }
    if characters.first() != Some(&0) {
        characters.insert(0, 0);
    }
    if kind == LINE {
        icu_rules(text, characters)
    } else {
        characters
    }
}

/// Two of ICU's line rules ICU4X lacks: no break after a hyphen that starts a
/// word (Unicode's LB20a), and a break after a slash before a digit when a
/// letter, not a digit or a space, comes before the slash.
fn icu_rules(text: &str, breaks: Vec<u32>) -> Vec<u32> {
    let characters: Vec<char> = text.chars().collect();
    let hyphen_starts_word = |i: usize| {
        i > 0 && i < characters.len() && matches!(characters[i - 1], '-' | '\u{2010}')
            && (i == 1 || matches!(characters[i - 2], ' ' | '\t' | '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{85}' | '\u{2028}' | '\u{2029}' | '\u{200b}' | '\u{a0}'))
            && characters[i].is_alphabetic()
    };
    let mut kept: Vec<u32> = breaks.into_iter().filter(|&i| !hyphen_starts_word(i as usize)).collect();
    for i in 2..characters.len() {
        if characters[i - 1] == '/' && characters[i].is_ascii_digit() && !characters[i - 2].is_ascii_digit() && !characters[i - 2].is_whitespace() {
            kept.push(i as u32);
        }
    }
    kept.sort_unstable();
    kept.dedup();
    kept
}

pub fn is_emoji(code_point: u32) -> bool {
    static SET: OnceLock<CodePointSetDataBorrowed<'static>> = OnceLock::new();
    SET.get_or_init(CodePointSetData::new::<Emoji>).contains32(code_point)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(text: &str) -> Vec<String> {
        let points = breaks(LINE, text);
        let characters: Vec<char> = text.chars().collect();
        points.windows(2).map(|pair| characters[pair[0] as usize..pair[1] as usize].iter().collect()).collect()
    }

    #[test]
    fn a_hyphen_that_starts_a_word_stays_with_it() {
        assert_eq!(lines("set -x now"), ["set ", "-x ", "now"]);
        assert_eq!(lines("well-known fact"), ["well-", "known ", "fact"]);
    }

    #[test]
    fn a_slash_before_a_number_breaks_after_a_letter_only() {
        assert_eq!(lines("HTTP/2 to"), ["HTTP/", "2 ", "to"]);
        assert_eq!(lines("800/500"), ["800/500"]);
    }

    #[test]
    fn boundaries_count_characters_not_bytes() {
        assert_eq!(breaks(GRAPHEME, "é👍🏽a"), [0, 1, 3, 4]);
        assert_eq!(breaks(WORD, "deux mots"), [0, 4, 5, 9]);
    }

    #[test]
    fn an_emoji_is_one() {
        assert!(is_emoji(0x1F44D) && !is_emoji('a' as u32));
    }
}
