<script lang="ts">
	// Game name with source > target languages, the three steps, then the tools.
	// It has no heading: each screen owns the page's single <h1>.
	import { t } from '$lib/i18n';
	import { languageName, languageShort } from '$lib/languages';
	import { project } from '$lib/stores';
	import StepNav from './StepNav.svelte';
	import ToolNav from './ToolNav.svelte';

	const APP_NAME = "Ren'Py Translation Studio";
</script>

<header>
	<div class="identity">
		<p>
			{#if $project}
				<span class="sr">{APP_NAME} — </span>
				<span class="game">{$project.gameName}</span>
				<span class="langs">
					<abbr title={languageName($project.sourceLanguage, $t)}
						>{languageShort($project.sourceLanguage)}</abbr
					>
					→
					{#if $project.targetLanguage}
						<abbr title={languageName($project.targetLanguage, $t)}
							>{languageShort($project.targetLanguage)}</abbr
						>
					{:else}
						?
					{/if}
				</span>
			{:else}
				<span class="game">{APP_NAME}</span>
			{/if}
		</p>
	</div>
	<StepNav />
	<div class="tools">
		<ToolNav />
	</div>
</header>

<style>
	header {
		display: flex;
		align-items: center;
		gap: 20px;
		height: 56px;
		padding: 0 14px 0 20px;
		border-bottom: 1px solid var(--line);
		background: var(--panel);
		flex: none;
	}

	.identity {
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
		flex: 1 1 0;
	}

	p {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
		margin: 0;
	}

	.game {
		font-weight: 700;
		font-size: 14.5px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.langs {
		font-size: 12.5px;
		color: var(--ink3);
		white-space: nowrap;
	}

	abbr {
		text-decoration: none;
	}

	.tools {
		flex: 1 1 0;
		display: flex;
		justify-content: flex-end;
	}
</style>
