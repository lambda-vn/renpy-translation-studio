<script lang="ts">
	// One translatable line: status, speaker, the five actions, the source and
	// the translation field, then whatever the line has to say (warning,
	// refusal, note, update by the assistant). The keyboard shortcuts live in
	// the page; the row only tells it where the focus is.
	import type { DuplicateStats, QualityIssuePayload, UnitPayload } from '$lib/api';
	import Kbd from '$lib/components/Kbd.svelte';
	import StatusGlyph from '$lib/components/StatusGlyph.svelte';
	import TokenText from '$lib/components/TokenText.svelte';
	import { t } from '$lib/i18n';
	import { qualityText } from '$lib/messages';
	import { statusDescription, type TranslationStatus } from '$lib/status';

	interface Props {
		unit: UnitPayload;
		draft: string;
		speakerLabel: string;
		sourceLang: string;
		targetLang: string;
		duplicates?: DuplicateStats;
		blocking: QualityIssuePayload[];
		warnings: QualityIssuePayload[];
		active: boolean;
		/** Written by another process a moment ago. */
		updatedByAssistant: boolean;
		translating: boolean;
		onactivate: () => void;
		oninput: (value: string) => void;
		ontranslate: () => void;
		oncopy: () => void;
		onclear: () => void;
		onflag: () => void;
		onvalidate: () => void;
		onspread: () => void;
		onnote: (note: string) => void;
	}

	let {
		unit,
		draft,
		speakerLabel,
		sourceLang,
		targetLang,
		duplicates,
		blocking,
		warnings,
		active,
		updatedByAssistant,
		translating,
		onactivate,
		oninput,
		ontranslate,
		oncopy,
		onclear,
		onflag,
		onvalidate,
		onspread,
		onnote
	}: Props = $props();

	const uid = $props.id();
	const fieldId = `tr-${uid}`;
	const warnId = `warn-${uid}`;
	const errId = `err-${uid}`;

	const status = $derived(unit.status as TranslationStatus);
	const hasError = $derived(blocking.length > 0);
	const label = $derived(
		$t('review.row_label', {
			n: unit.sourceLine,
			status: statusDescription(status, $t, { flagged: unit.needsReview, error: hasError })
		})
	);
	const describedBy = $derived(
		[hasError ? errId : '', warnings.length > 0 ? warnId : ''].filter(Boolean).join(' ') ||
			undefined
	);
	const validated = $derived(status === 'human_validated');
	const others = $derived(duplicates ? duplicates.total - 1 : 0);

	let field: HTMLTextAreaElement | undefined = $state();

	// The field grows with its content instead of scrolling.
	$effect(() => {
		void draft;
		if (!field) return;
		field.style.height = 'auto';
		field.style.height = `${field.scrollHeight + 2}px`;
	});

	function duplicatesTitle(): string {
		if (!duplicates) return '';
		const elsewhere = duplicates.otherFiles;
		const here = duplicates.total - 1 - elsewhere;
		const counts =
			elsewhere > 0
				? $t('review.duplicates_split_tooltip', { here, elsewhere })
				: $t('review.duplicates_here_tooltip', { here });
		return `${counts} ${$t('review.duplicates_badge_action')}`;
	}

	function fieldKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape' && !event.ctrlKey && !event.altKey && !event.shiftKey) {
			event.stopPropagation();
			field?.blur();
		}
	}
</script>

<li class="row" class:active class:mcp={updatedByAssistant} data-row={unit.blockId}>
	<div class="glyphs">
		<span class="sr">{label}</span>
		<StatusGlyph kind={status} />
		{#if unit.needsReview}<StatusGlyph kind="flag" />{/if}
		{#if hasError}<StatusGlyph kind="error" />{/if}
	</div>

	<div class="head">
		{#if unit.speaker}
			<span class="speaker">{speakerLabel}</span>
		{:else if !unit.blockId.startsWith('strings_')}
			<!-- A `strings` block is interface text (menus, buttons), not a line nobody speaks. -->
			<span class="speaker narration">{$t('review.narration')}</span>
		{/if}
		<span class="mono lineno">{$t('review.line_n', { n: unit.sourceLine })}</span>
		{#if others > 0}
			<button
				type="button"
				class="dupes mono"
				title={duplicatesTitle()}
				aria-label={`${$t('review.duplicates_aria', { n: others, line: unit.sourceLine })}`}
				onclick={onspread}
			>
				<span aria-hidden="true">↔ {others}</span>
			</button>
		{/if}
		<div class="acts">
			<button
				type="button"
				class="ab"
				disabled={translating}
				aria-busy={translating}
				aria-label={$t('review.act_translate', { n: unit.sourceLine })}
				title={$t('review.translate_unit_tooltip')}
				onclick={ontranslate}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.4"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
					><path
						d="M2.5 3.5h6M5.5 2v1.5M7.5 3.5c-.6 2.6-2.4 4.7-5 5.7M4.2 5.6c.8 1.4 2 2.5 3.5 3.1M8.5 14l2.75-6.5L14 14M9.4 12h3.7"
					/></svg
				>
			</button>
			<button
				type="button"
				class="ab"
				aria-label={$t('review.act_copy', { n: unit.sourceLine })}
				title="{$t('review.copy_source')} (Ctrl+D)"
				onclick={oncopy}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.4"
					stroke-linejoin="round"
					aria-hidden="true"
					><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" /><path
						d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"
					/></svg
				>
			</button>
			<button
				type="button"
				class="ab"
				aria-label={$t('review.act_clear', { n: unit.sourceLine })}
				title={$t('review.clear_field')}
				onclick={onclear}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.4"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
					><path d="M6.2 3.5H13.5v9H6.2L2.5 8z" /><path
						d="M8.3 6.3l3.2 3.4M11.5 6.3L8.3 9.7"
					/></svg
				>
			</button>
			<button
				type="button"
				class="ab flag"
				aria-pressed={unit.needsReview}
				aria-label={$t('review.act_flag', { n: unit.sourceLine })}
				title={$t('review.needs_review_tooltip')}
				onclick={onflag}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.4"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M3.5 14V2.5M3.5 3h8.5l-2 3 2 3H3.5" /></svg
				>
			</button>
			<button
				type="button"
				class="ab ok"
				aria-pressed={validated}
				aria-label={$t('review.act_validate', { n: unit.sourceLine })}
				title={$t('review.validate')}
				onclick={onvalidate}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.7"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" /></svg
				>
			</button>
		</div>
	</div>

	<p class="txt source"><TokenText text={unit.sourceText} lang={sourceLang} /></p>

	<div class="target">
		<label class="sr" for={fieldId}>{$t('review.translation_of', { n: unit.sourceLine })}</label>
		<textarea
			id={fieldId}
			bind:this={field}
			class="ta"
			rows="1"
			lang={targetLang}
			data-block-id={unit.blockId}
			value={draft}
			placeholder={$t('review.not_translated_yet')}
			aria-describedby={describedBy}
			aria-invalid={hasError ? 'true' : undefined}
			onfocus={onactivate}
			oninput={(e) => oninput(e.currentTarget.value)}
			onkeydown={fieldKeydown}
		></textarea>

		{#if warnings.length > 0}
			<p class="msg warn" id={warnId}>
				<StatusGlyph kind="warning" />
				<span
					><span class="sr">{$t('status.warning')} : </span>{warnings
						.map((w) => qualityText($t, w))
						.join(' ')}</span
				>
			</p>
		{/if}

		{#if active}
			<p class="msg hint">
				<span><Kbd shortcut="validate" /> {$t('review.hint_validate')}</span>
				<span><Kbd keys="Escape" /> {$t('review.hint_leave')}</span>
			</p>
		{/if}

		{#if hasError}
			<p class="msg box err" id={errId} role="alert">
				<StatusGlyph kind="error" cutout="var(--errWeak)" />
				<span
					><strong>{$t('review.validation_refused')}</strong>
					{blocking.map((b) => qualityText($t, b)).join(' ')}</span
				>
			</p>
		{/if}

		{#if unit.needsReview}
			<div class="msg box note">
				<StatusGlyph kind="flag" cutout="var(--flagWeak)" />
				<label class="sr" for="note-{uid}">{$t('review.note_label', { n: unit.sourceLine })}</label>
				<input
					id="note-{uid}"
					type="text"
					data-block-id={unit.blockId}
					value={unit.note ?? ''}
					placeholder={$t('review.note_hint')}
					onfocus={onactivate}
					onchange={(e) => onnote(e.currentTarget.value)}
				/>
			</div>
		{/if}

		{#if updatedByAssistant}
			<p class="msg mcpmsg">
				<StatusGlyph kind="ai_suggested" />
				<span>{$t('review.updated_by_assistant')}</span>
			</p>
		{/if}
	</div>
</li>

<style>
	.row {
		display: grid;
		grid-template-columns: 22px minmax(0, 1fr) minmax(0, 1fr);
		column-gap: 24px;
		row-gap: 2px;
		padding: 8px 16px 12px;
		margin: 0 -16px;
		border-bottom: 1px solid var(--line);
		border-radius: 12px;
		transition: background-color 0.6s;
	}

	.row:hover {
		background: var(--hover);
	}

	.row.active {
		background: var(--accWeak);
		border-bottom-color: transparent;
	}

	.row.mcp {
		background: var(--mcpWeak);
	}

	.glyphs {
		grid-column: 1;
		grid-row: 1;
		display: flex;
		flex-direction: column;
		gap: 6px;
		align-items: center;
		padding-top: 6px;
	}

	.head {
		grid-column: 2 / 4;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 26px;
	}

	.speaker {
		font-size: 13px;
		font-weight: 600;
		color: var(--ink2);
	}

	.speaker.narration {
		font-style: italic;
		font-weight: 400;
		color: var(--ink3);
	}

	.lineno {
		font-size: 11.5px;
		color: var(--ink3);
	}

	.dupes {
		display: inline-flex;
		align-items: center;
		height: 22px;
		padding: 0 7px;
		border: 1px solid var(--line2);
		border-radius: 999px;
		background: transparent;
		font-size: 11.5px;
		color: var(--ink3);
	}

	.dupes:hover {
		background: var(--sunken);
		color: var(--ink);
	}

	.acts {
		display: flex;
		gap: 2px;
		margin-left: auto;
		opacity: 0;
	}

	.row:hover .acts,
	.row:focus-within .acts,
	.row.active .acts {
		opacity: 1;
	}

	.ab {
		width: 26px;
		height: 26px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--ink3);
		padding: 0;
	}

	.ab:hover:not(:disabled) {
		background: var(--sunken);
		color: var(--ink);
	}

	.ab:disabled {
		opacity: 0.45;
	}

	.ab.flag[aria-pressed='true'] {
		color: var(--flag);
	}

	.ab.ok[aria-pressed='true'] {
		color: var(--s-ok);
	}

	.txt {
		font-family: var(--font-text);
		font-size: 15px;
		line-height: 1.6;
		margin: 0;
		min-width: 0;
	}

	.source {
		grid-column: 2;
		grid-row: 2;
	}

	.target {
		grid-column: 3;
		grid-row: 2;
		min-width: 0;
	}

	.ta {
		display: block;
		min-height: 40px;
		resize: none;
		overflow: hidden;
		border: 1px solid transparent;
		border-radius: var(--r-md);
		padding: 8px 11px;
		margin: -9px -12px;
		width: calc(100% + 24px);
		background: transparent;
		font-family: var(--font-text);
		font-size: 15px;
		line-height: 1.6;
		color: var(--ink);
		white-space: pre-wrap;
	}

	.ta:hover {
		border-color: var(--line2);
	}

	.ta:focus,
	.ta:focus-visible {
		border-color: var(--acc);
		background: var(--panel);
		box-shadow: 0 0 0 3px var(--accRing);
		outline: 0;
	}

	.ta::placeholder {
		font-family: var(--font-ui);
		font-size: 13.5px;
		font-style: italic;
		color: var(--ink3);
	}

	.ta[aria-invalid='true'] {
		border-color: var(--err);
	}

	.msg {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		margin: 10px 0 0;
		font-size: 13px;
		line-height: 1.5;
		color: var(--ink2);
	}

	.msg > :global(svg) {
		margin-top: 2px;
	}

	.msg.box {
		padding: 8px 11px;
		border-radius: 8px;
		color: var(--ink);
	}

	.msg.warn {
		color: var(--warn);
	}

	.msg.err {
		background: var(--errWeak);
	}

	.msg.err strong {
		font-weight: 600;
	}

	.msg.note {
		background: var(--flagWeak);
		align-items: center;
	}

	.msg.note input {
		flex: 1;
		height: auto;
		padding: 0;
		border: 0;
		border-radius: 0;
		background: transparent;
		box-shadow: none;
		font-size: 13px;
	}

	.msg.note input:focus-visible {
		outline: 2px solid var(--acc);
		outline-offset: 2px;
		box-shadow: none;
	}

	.msg.hint {
		flex-wrap: wrap;
		gap: 6px 16px;
		font-size: 12.5px;
		color: var(--ink3);
	}

	.msg.hint span {
		display: inline-flex;
		gap: 6px;
		align-items: center;
	}

	.msg.mcpmsg {
		font-size: 12.5px;
		color: var(--mcp);
	}

	@media (max-width: 860px) {
		.row {
			grid-template-columns: 22px minmax(0, 1fr);
		}
		.head {
			grid-column: 2;
		}
		.source {
			grid-column: 2;
		}
		.target {
			grid-column: 2;
			grid-row: 3;
		}
	}
</style>
