// Splits a game string into plain text, {tags} and [interpolations] so the
// UI can draw the latter two as chips. Output is data, never HTML: game text
// is third-party content and must only ever reach the DOM as text nodes.

export type TokenKind = 'text' | 'tag' | 'var';

export interface TextSegment {
	kind: TokenKind;
	text: string;
}

// `{{` and `[[` are Ren'Py's escapes for a literal brace/bracket: consumed
// first so what follows them is not mistaken for a token. An interpolation
// may hold one level of nested brackets ([items[0]]).
const TOKEN = /\{\{|\[\[|\{[^{}]*\}|\[(?:[^[\]]|\[[^[\]]*\])*\]/g;

export function tokenize(text: string): TextSegment[] {
	const segments: TextSegment[] = [];
	let last = 0;
	const push = (kind: TokenKind, value: string) => {
		if (!value) return;
		const previous = segments[segments.length - 1];
		if (kind === 'text' && previous?.kind === 'text') previous.text += value;
		else segments.push({ kind, text: value });
	};
	for (const match of text.matchAll(TOKEN)) {
		const value = match[0];
		push('text', text.slice(last, match.index));
		if (value === '{{' || value === '[[') push('text', value);
		else push(value.startsWith('{') ? 'tag' : 'var', value);
		last = match.index + value.length;
	}
	push('text', text.slice(last));
	return segments;
}
