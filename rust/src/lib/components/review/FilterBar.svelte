<script lang="ts">
	// Search, status chips (aria-pressed buttons) and the speaker selector.
	import type { SpeakerEntry } from '$lib/api';
	import ContextMenu, { type MenuEntry } from '$lib/components/ContextMenu.svelte';
	import Kbd from '$lib/components/Kbd.svelte';
	import StatusGlyph from '$lib/components/StatusGlyph.svelte';
	import { t } from '$lib/i18n';
	import type { StatusFilter } from '$lib/review-state';
	import type { GlyphKind } from '$lib/status';

	interface Props {
		filter: StatusFilter;
		/** Lines per chip in the open file; absent when unknown. */
		counts: Partial<Record<StatusFilter, number>>;
		speakers: SpeakerEntry[];
		speaker: string;
		search: string;
		searchInput?: HTMLInputElement;
		onfilter: (filter: StatusFilter) => void;
		onspeaker: (speaker: string) => void;
		onsearch: (value: string, immediate: boolean) => void;
	}

	let {
		filter,
		counts,
		speakers,
		speaker,
		search = $bindable(),
		searchInput = $bindable(),
		onfilter,
		onspeaker,
		onsearch
	}: Props = $props();

	// The speaker list is a menu rather than a <select>: a native select
	// opens the operating system's own list, which no stylesheet reaches.
	let speakerOpen = $state(false);
	let speakerButton: HTMLButtonElement | undefined = $state();

	const speakerName = $derived(
		speakers.find((entry) => entry.variable === speaker)?.label ?? $t('review.filter_character_all')
	);

	const speakerItems: MenuEntry[] = $derived([
		{ label: $t('review.filter_character_all'), checked: speaker === '', onselect: () => onspeaker('') },
		{ separator: true },
		...speakers.map((entry) => ({
			label: entry.label,
			checked: speaker === entry.variable,
			onselect: () => onspeaker(entry.variable)
		}))
	]);

	interface Chip {
		id: StatusFilter;
		label: string;
		glyph: GlyphKind | null;
		separated?: boolean;
	}

	const chips: Chip[] = $derived([
		{ id: 'all', label: $t('review.filter_all'), glyph: null },
		{ id: 'not_translated', label: $t('review.filter_not_translated'), glyph: 'not_translated' },
		{ id: 'draft', label: $t('review.filter_draft'), glyph: 'draft' },
		{ id: 'imported', label: $t('review.filter_imported'), glyph: 'imported' },
		{ id: 'ai_suggested', label: $t('review.filter_ai_suggested'), glyph: 'ai_suggested' },
		{ id: 'human_validated', label: $t('review.filter_validated'), glyph: 'human_validated' },
		{ id: 'flagged', label: $t('review.filter_needs_review'), glyph: 'flag', separated: true },
		{ id: 'errors', label: $t('review.filter_errors'), glyph: 'error' }
	]);
</script>

<form role="search" aria-label={$t('review.filter_label')} onsubmit={(e) => {
	e.preventDefault();
	onsearch(search, true);
}}>
	<label class="field pill search">
		<svg
			class="ico"
			viewBox="0 0 16 16"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			aria-hidden="true"><circle cx="7" cy="7" r="4.25" /><path d="M10.2 10.2L13.5 13.5" /></svg
		>
		<span class="sr">{$t('review.search_label')}</span>
		<input
			type="search"
			bind:this={searchInput}
			bind:value={search}
			placeholder={$t('review.search_placeholder')}
			oninput={(e) => onsearch(e.currentTarget.value, false)}
		/>
		<Kbd shortcut="search" />
	</label>

	<div role="group" aria-label={$t('review.status_group')} class="chips">
		{#each chips as chip (chip.id)}
			{#if chip.separated}<span class="sep" aria-hidden="true"></span>{/if}
			<button
				type="button"
				class="flt"
				aria-pressed={filter === chip.id}
				title={chip.label}
				onclick={() => onfilter(chip.id)}
			>
				{#if chip.glyph}
					<StatusGlyph kind={chip.glyph} />
					<span class="sr">{chip.label}</span>
				{:else}
					<span>{chip.label}</span>
				{/if}
				{#if counts[chip.id] !== undefined}<span class="n">{counts[chip.id]}</span>{/if}
			</button>
		{/each}
	</div>

	{#if speakers.length > 0}
		<button
			type="button"
			class="field pill speaker"
			class:on={speaker !== ''}
			bind:this={speakerButton}
			aria-haspopup="menu"
			aria-expanded={speakerOpen}
			onclick={() => (speakerOpen = !speakerOpen)}
		>
			<span class="lbl-in">{$t('review.filter_character_hint')}</span>
			<span class="val">{speakerName}</span>
			<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 6.5L8 10l3.5-3.5" /></svg>
		</button>
		<ContextMenu
			bind:open={speakerOpen}
			label={$t('review.filter_character_hint')}
			items={speakerItems}
			anchor={speakerButton}
		/>
	{/if}
</form>

<style>
	form {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px 16px;
		margin: 0;
	}

	.search {
		flex: 0 1 280px;
		min-width: 200px;
	}

	.speaker {
		flex: 0 0 auto;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		max-width: 260px;
		cursor: pointer;
		font: inherit;
		text-align: left;
	}

	.speaker:hover {
		border-color: var(--ink3);
	}

	.speaker.on {
		background: var(--accWeak);
		border-color: var(--accLine);
	}

	.lbl-in {
		font-size: 13px;
		color: var(--ink3);
	}

	.val {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13.5px;
		font-weight: 500;
		color: var(--ink);
	}

	.speaker.on .val {
		color: var(--acc7);
	}

	.chev {
		flex: 0 0 auto;
		width: 14px;
		height: 14px;
		fill: none;
		stroke: var(--ink3);
		stroke-width: 1.6;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px;
	}

	.sep {
		width: 1px;
		height: 18px;
		background: var(--line);
		margin: 0 6px;
	}

	.flt {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 30px;
		padding: 0 10px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		font-size: 13px;
		color: var(--ink2);
	}

	.flt:hover {
		background: var(--sunken);
	}

	.flt[aria-pressed='true'] {
		background: var(--accWeak);
		color: var(--acc7);
		font-weight: 600;
	}

	.n {
		font-family: var(--font-mono);
		font-size: 12px;
	}
</style>
