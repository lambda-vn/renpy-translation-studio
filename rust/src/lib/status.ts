// Translation statuses as the backend names them, plus the glyph kinds that
// are not statuses. Status is never carried by colour alone: every glyph has
// a distinct shape and a screen-reader label.

import type { Translate } from './i18n';

export type TranslationStatus =
	| 'not_translated'
	| 'draft'
	| 'imported'
	| 'ai_suggested'
	| 'human_validated';

export type GlyphKind = TranslationStatus | 'flag' | 'error' | 'warning';

const LABEL_KEYS: Record<GlyphKind, string> = {
	not_translated: 'status.not_translated',
	draft: 'status.draft',
	imported: 'status.imported',
	ai_suggested: 'status.ai_suggested',
	human_validated: 'status.human_validated',
	flag: 'status.flag',
	error: 'status.error',
	warning: 'status.warning'
};

/** Localised name of a status (or marker), for `.sr` text and tooltips. */
export function statusLabel(kind: GlyphKind, t: Translate): string {
	return t(LABEL_KEYS[kind]);
}

/** "Not translated, flagged": the status first, then the markers that apply. */
export function statusDescription(
	status: TranslationStatus,
	t: Translate,
	markers: { flagged?: boolean; error?: boolean } = {}
): string {
	const parts = [statusLabel(status, t)];
	if (markers.flagged) parts.push(statusLabel('flag', t));
	if (markers.error) parts.push(statusLabel('error', t));
	return parts.join(', ');
}
