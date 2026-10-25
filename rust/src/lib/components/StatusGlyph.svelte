<script lang="ts">
	// One shape per status, so nothing is told by colour alone. The glyph is
	// decorative (aria-hidden): pair it with text, or with `statusLabel()` /
	// `statusDescription()` from $lib/status in a `.sr` span.
	import type { GlyphKind } from '$lib/status';

	interface Props {
		kind: GlyphKind;
		/** Pixel size; the mockups use 14 (rows, chips) and 16. */
		size?: number;
		/** Colour of the check/exclamation cut-out; use the surface the glyph sits on. */
		cutout?: string;
	}

	let { kind, size = 14, cutout = 'var(--panel)' }: Props = $props();

	const colors: Record<GlyphKind, string> = {
		not_translated: 'var(--s-none)',
		draft: 'var(--s-draft)',
		imported: 'var(--s-imp)',
		ai_suggested: 'var(--s-ai)',
		human_validated: 'var(--s-ok)',
		flag: 'var(--flag)',
		error: 'var(--err)',
		warning: 'var(--warn)'
	};
</script>

<svg
	class="glyph"
	width={size}
	height={size}
	viewBox="0 0 16 16"
	aria-hidden="true"
	focusable="false"
	style:color={colors[kind]}
>
	{#if kind === 'not_translated'}
		<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6" />
	{:else if kind === 'draft'}
		<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6" />
		<path d="M8 2.5a5.5 5.5 0 0 0 0 11z" fill="currentColor" />
	{:else if kind === 'imported'}
		<path d="M8 2L14 8 8 14 2 8z" fill="currentColor" />
	{:else if kind === 'ai_suggested'}
		<path d="M8 1.5L9.6 6.4 14.5 8 9.6 9.6 8 14.5 6.4 9.6 1.5 8 6.4 6.4z" fill="currentColor" />
	{:else if kind === 'human_validated'}
		<circle cx="8" cy="8" r="6.5" fill="currentColor" />
		<path
			d="M5 8.2l2 2 4-4.2"
			fill="none"
			stroke={cutout}
			stroke-width="1.7"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	{:else if kind === 'flag'}
		<path d="M4 14.5V2.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
		<path d="M4 2.5h8l-1.8 3 1.8 3H4z" fill="currentColor" />
	{:else if kind === 'error'}
		<path d="M8 1.8L14.8 13.8H1.2z" fill="currentColor" />
		<path d="M8 6.3v3.4M8 11.6v.1" stroke={cutout} stroke-width="1.7" stroke-linecap="round" />
	{:else if kind === 'warning'}
		<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.4" />
		<path d="M8 4.8v3.8M8 11v.1" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
	{/if}
</svg>

<style>
	.glyph {
		flex: none;
		display: block;
	}
</style>
