//! Central language list: the single place to add a supported language.
//!
//! Port of `core/languages.py`. Each [`Language`] entry drives the setup
//! dropdowns, the recognized-language check, and the codes sent to MT
//! providers. To support a new language, append one entry to `LANGUAGES`
//! — nothing else to change.
//!
//! `code` doubles as the Ren'Py `tl/<code>/` folder name. Regional
//! variants (e.g. `english_us`) keep a distinct folder name but map to
//! their base ISO code for MT providers, which mostly ignore regions.
//!
//! `localized_label()` (the UI-facing name in the interface's own
//! language) is not ported here: it depends on i18n, which belongs to
//! the UI phase. This module only carries the data and `label`, the
//! English fallback every screen already falls back to when a locale
//! doesn't translate a language yet.

pub struct Language {
    pub code: &'static str,
    pub label: &'static str,
    pub iso: &'static str,
    pub iso_long: Option<&'static str>,
    pub deepl: Option<&'static str>,
}

impl Language {
    /// The regional tag, falling back to the short ISO code.
    pub fn long_code(&self) -> &'static str {
        self.iso_long.unwrap_or(self.iso)
    }
}

pub const LANGUAGES: &[Language] = &[
    Language {
        code: "english",
        label: "English",
        iso: "en",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "english_us",
        label: "English (US)",
        iso: "en",
        iso_long: Some("en-US"),
        deepl: None,
    },
    Language {
        code: "english_gb",
        label: "English (UK)",
        iso: "en",
        iso_long: Some("en-GB"),
        deepl: None,
    },
    Language {
        code: "french",
        label: "French",
        iso: "fr",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "german",
        label: "German",
        iso: "de",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "spanish",
        label: "Spanish",
        iso: "es",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "italian",
        label: "Italian",
        iso: "it",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "portuguese",
        label: "Portuguese",
        iso: "pt",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "brazilian",
        label: "Portuguese (Brazil)",
        iso: "pt",
        iso_long: Some("pt-BR"),
        deepl: None,
    },
    Language {
        code: "dutch",
        label: "Dutch",
        iso: "nl",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "polish",
        label: "Polish",
        iso: "pl",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "russian",
        label: "Russian",
        iso: "ru",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "ukrainian",
        label: "Ukrainian",
        iso: "uk",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "turkish",
        label: "Turkish",
        iso: "tr",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "arabic",
        label: "Arabic",
        iso: "ar",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "japanese",
        label: "Japanese",
        iso: "ja",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "korean",
        label: "Korean",
        iso: "ko",
        iso_long: None,
        deepl: None,
    },
    Language {
        code: "schinese",
        label: "Chinese (Simplified)",
        iso: "zh",
        iso_long: Some("zh-Hans"),
        deepl: None,
    },
    Language {
        code: "tchinese",
        label: "Chinese (Traditional)",
        iso: "zt",
        iso_long: Some("zh-Hant"),
        deepl: Some("ZH"),
    },
];

/// Return the [`Language`] entry for an internal identifier, if known.
///
/// `code` is matched case-insensitively.
pub fn get_language(code: &str) -> Option<&'static Language> {
    let code = code.to_lowercase();
    LANGUAGES.iter().find(|lang| lang.code == code)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn get_language_is_case_insensitive() {
        assert!(get_language("FRENCH").is_some());
        assert_eq!(get_language("french").unwrap().iso, "fr");
    }

    #[test]
    fn get_language_returns_none_for_unknown_code() {
        assert!(get_language("klingon").is_none());
    }

    #[test]
    fn long_code_falls_back_to_iso() {
        assert_eq!(get_language("french").unwrap().long_code(), "fr");
        assert_eq!(get_language("english_us").unwrap().long_code(), "en-US");
    }

    #[test]
    fn codes_are_unique() {
        let mut codes: Vec<&str> = LANGUAGES.iter().map(|l| l.code).collect();
        let before = codes.len();
        codes.sort_unstable();
        codes.dedup();
        assert_eq!(codes.len(), before, "duplicate language code in LANGUAGES");
    }
}
