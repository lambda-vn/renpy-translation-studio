// The single declaration of the keyboard shortcuts (same table as 1.x).
// The help dialog lists it and the screens bind it, so a shortcut can't be
// bound without being documented.
//
//   <svelte:window onkeydown={(e) => { if (matches('save', e)) { e.preventDefault(); save(); } }} />
//
// Modifiers are matched exactly: Ctrl+Enter and Ctrl+Shift+Enter are two
// shortcuts that never fire together. Ctrl also accepts Cmd (macOS).

import type { Translate } from './i18n';

export type ShortcutScope = 'global' | 'review';

export interface Shortcut {
	id: string;
	/** `KeyboardEvent.key` value ("F1", "Enter", "ArrowUp", "s"); letters are compared case-insensitively. */
	key: string;
	ctrl?: boolean;
	shift?: boolean;
	alt?: boolean;
	/** i18n key naming the action in the help dialog. */
	labelKey: string;
	scope: ShortcutScope;
}

export const SHORTCUTS: readonly Shortcut[] = [
	{ id: 'help', key: 'F1', labelKey: 'help.shortcut_help', scope: 'global' },
	{ id: 'escape', key: 'Escape', labelKey: 'help.shortcut_escape', scope: 'global' },
	{ id: 'search', key: 'f', ctrl: true, labelKey: 'help.shortcut_search', scope: 'review' },
	{ id: 'save', key: 's', ctrl: true, labelKey: 'help.shortcut_save', scope: 'review' },
	{ id: 'validate', key: 'Enter', ctrl: true, labelKey: 'help.shortcut_validate', scope: 'review' },
	{
		id: 'spread_duplicates',
		key: 'Enter',
		ctrl: true,
		shift: true,
		labelKey: 'help.shortcut_spread_duplicates',
		scope: 'review'
	},
	{ id: 'copy_source', key: 'd', ctrl: true, labelKey: 'help.shortcut_copy_source', scope: 'review' },
	{ id: 'needs_review', key: 'm', ctrl: true, labelKey: 'help.shortcut_needs_review', scope: 'review' },
	{ id: 'prev_row', key: 'ArrowUp', alt: true, labelKey: 'help.shortcut_prev_row', scope: 'review' },
	{ id: 'next_row', key: 'ArrowDown', alt: true, labelKey: 'help.shortcut_next_row', scope: 'review' },
	{
		id: 'prev_file',
		key: 'ArrowUp',
		alt: true,
		shift: true,
		labelKey: 'help.shortcut_prev_file',
		scope: 'review'
	},
	{
		id: 'next_file',
		key: 'ArrowDown',
		alt: true,
		shift: true,
		labelKey: 'help.shortcut_next_file',
		scope: 'review'
	},
	{ id: 'prev_page', key: 'ArrowLeft', alt: true, labelKey: 'help.shortcut_prev_page', scope: 'review' },
	{ id: 'next_page', key: 'ArrowRight', alt: true, labelKey: 'help.shortcut_next_page', scope: 'review' },
	{ id: 'file_menu', key: 'ContextMenu', labelKey: 'help.shortcut_file_menu', scope: 'review' }
];

export function getShortcut(id: string): Shortcut {
	const found = SHORTCUTS.find((shortcut) => shortcut.id === id);
	if (!found) throw new Error(`Unknown shortcut: ${id}`);
	return found;
}

export function shortcutsFor(scope: ShortcutScope): Shortcut[] {
	return SHORTCUTS.filter((shortcut) => shortcut.scope === scope);
}

function fires(shortcut: Shortcut, event: KeyboardEvent): boolean {
	return (
		event.key.toLowerCase() === shortcut.key.toLowerCase() &&
		(event.ctrlKey || event.metaKey) === Boolean(shortcut.ctrl) &&
		event.shiftKey === Boolean(shortcut.shift) &&
		event.altKey === Boolean(shortcut.alt)
	);
}

/** Does this key event fire that shortcut? Caller decides about preventDefault. */
export function matches(id: string, event: KeyboardEvent): boolean {
	return fires(getShortcut(id), event);
}

/** The shortcut a key event fires, if any; restrict to one scope to bind a screen's table. */
export function findShortcut(event: KeyboardEvent, scope?: ShortcutScope): Shortcut | undefined {
	return SHORTCUTS.find((shortcut) => (!scope || shortcut.scope === scope) && fires(shortcut, event));
}

// Display -------------------------------------------------------------

const KEY_NAMES: Record<string, string> = {
	Escape: 'help.key_escape',
	Enter: 'help.key_enter',
	ContextMenu: 'help.key_context_menu',
	Ctrl: 'help.key_ctrl',
	Shift: 'help.key_shift',
	Alt: 'help.key_alt'
};

const KEY_GLYPHS: Record<string, string> = {
	ArrowLeft: '←',
	ArrowRight: '→',
	ArrowUp: '↑',
	ArrowDown: '↓'
};

const MAC_GLYPHS: Record<string, string> = { Ctrl: '⌘', Shift: '⇧', Alt: '⌥' };

export function isMac(): boolean {
	return typeof navigator !== 'undefined' && /mac/i.test(navigator.platform);
}

/** "Ctrl+Shift+Enter" as canonical tokens: ["Ctrl", "Shift", "Enter"]. */
export function shortcutParts(shortcut: Shortcut): string[] {
	const key = shortcut.key.length === 1 ? shortcut.key.toUpperCase() : shortcut.key;
	return [
		...(shortcut.ctrl ? ['Ctrl'] : []),
		...(shortcut.shift ? ['Shift'] : []),
		...(shortcut.alt ? ['Alt'] : []),
		key
	];
}

/** Localised label of one canonical token ("Enter" -> "Entrée", "ArrowUp" -> "↑"). */
export function keyLabel(token: string, t: Translate, mac = isMac()): string {
	if (mac && MAC_GLYPHS[token]) return MAC_GLYPHS[token];
	if (KEY_GLYPHS[token]) return KEY_GLYPHS[token];
	return KEY_NAMES[token] ? t(KEY_NAMES[token]) : token;
}
