//! Character glossary entries.

use rusqlite::{params, Connection};

/// A glossary entry: a Ren'Py character variable and how it is shown.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Character {
    pub id: i64,
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

/// Insert or update a character by its Ren'Py variable name.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn upsert_character(
    conn: &Connection,
    variable: &str,
    display_name: &str,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT INTO characters (variable, display_name) VALUES (?1, ?2) \
         ON CONFLICT(variable) DO UPDATE SET display_name = excluded.display_name",
        params![variable, display_name],
    )?;
    Ok(())
}

/// Update free-form notes (gender, register, remarks…) for a character.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn update_character_notes(
    conn: &Connection,
    variable: &str,
    notes: &str,
) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE characters SET notes = ?1 WHERE variable = ?2",
        params![notes, variable],
    )?;
    Ok(())
}

/// All characters, ordered by display name.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn get_all_characters(conn: &Connection) -> rusqlite::Result<Vec<Character>> {
    let mut stmt = conn.prepare(
        "SELECT id, variable, display_name, notes FROM characters ORDER BY display_name",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(Character {
            id: row.get(0)?,
            variable: row.get(1)?,
            display_name: row.get(2)?,
            notes: row.get(3)?,
        })
    })?;
    rows.collect()
}

/// Remove a character entry.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn delete_character(conn: &Connection, variable: &str) -> rusqlite::Result<()> {
    conn.execute(
        "DELETE FROM characters WHERE variable = ?1",
        params![variable],
    )?;
    Ok(())
}

/// Delete every character in one statement; returns how many there were.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn delete_all_characters(conn: &Connection) -> rusqlite::Result<usize> {
    conn.execute("DELETE FROM characters", [])
}

#[cfg(test)]
mod tests {
    use super::super::meta::{get_project_meta, set_project_meta, UNIVERSE_SUMMARY_KEY};
    use super::super::test_support::open_temp;
    use super::*;

    #[test]
    fn character_and_project_meta_roundtrip() {
        let db = open_temp();
        upsert_character(db.conn(), "e", "Eileen").unwrap();
        update_character_notes(db.conn(), "e", "narrator, formal register").unwrap();
        upsert_character(db.conn(), "e", "Eileen Renard").unwrap();

        let characters = get_all_characters(db.conn()).unwrap();
        assert_eq!(characters.len(), 1);
        assert_eq!(characters[0].display_name, "Eileen Renard");
        assert_eq!(
            characters[0].notes.as_deref(),
            Some("narrator, formal register")
        );

        delete_character(db.conn(), "e").unwrap();
        assert!(get_all_characters(db.conn()).unwrap().is_empty());

        assert_eq!(
            get_project_meta(db.conn(), UNIVERSE_SUMMARY_KEY).unwrap(),
            None
        );
        set_project_meta(db.conn(), UNIVERSE_SUMMARY_KEY, "A fantasy world.").unwrap();
        assert_eq!(
            get_project_meta(db.conn(), UNIVERSE_SUMMARY_KEY)
                .unwrap()
                .as_deref(),
            Some("A fantasy world.")
        );
    }

    #[test]
    fn delete_all_characters_empties_the_glossary() {
        let db = open_temp();
        upsert_character(db.conn(), "e", "Eileen").unwrap();
        upsert_character(db.conn(), "l", "Lucy").unwrap();

        assert_eq!(delete_all_characters(db.conn()).unwrap(), 2);
        assert!(get_all_characters(db.conn()).unwrap().is_empty());
    }
}
