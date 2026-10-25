<script lang="ts">
	// Game text with {tags} and [interpolations] drawn as mono chips. Rendered
	// strictly as text nodes: the string is third-party content, never {@html}.
	import { tokenize } from '$lib/tokenize';

	interface Props {
		text: string;
		/** Language of the text, for the `lang` attribute (RGAA 8.7): "en" for a source. */
		lang?: string;
	}

	let { text, lang }: Props = $props();

	const segments = $derived(tokenize(text));
</script>

<span class="game-text" {lang}
	>{#each segments as segment, index (index)}{#if segment.kind === 'text'}{segment.text}{:else}<span
				class={segment.kind === 'tag' ? 'tk' : 'tv'}
				translate="no">{segment.text}</span
			>{/if}{/each}</span
>

<style>
	.game-text {
		font-family: var(--font-text);
		font-size: 15px;
		line-height: 1.6;
		color: var(--ink);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.tk,
	.tv {
		font-family: var(--font-mono);
		font-size: 12.5px;
		border-radius: 4px;
		padding: 1px 4px;
	}

	.tk {
		color: var(--tag);
		background: var(--tagBg);
	}

	.tv {
		color: var(--var);
		background: var(--varBg);
	}
</style>
