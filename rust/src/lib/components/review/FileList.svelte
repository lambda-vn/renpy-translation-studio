<script lang="ts" module>
	import type { FileEntry } from '$lib/api';

	export interface FileMenuRequest {
		file: FileEntry;
		/** Pointer position, or the focused button when the keyboard asked. */
		x: number;
		y: number;
		anchor: HTMLElement | null;
	}
</script>

<script lang="ts">
	// The files aside: project progress, then one button per file. Right click,
	// the Menu key and Shift+F10 ask the parent for the file's actions.
	import type { ProgressPayload } from '$lib/api';
	import { t } from '$lib/i18n';
	import { matches } from '$lib/shortcuts';

	interface Props {
		files: FileEntry[];
		selected: string;
		progress: ProgressPayload | null;
		/** Lines matching the filters in a file; null when nothing narrows the view. */
		matchOf: (file: FileEntry) => number | null;
		onselect: (sourceFile: string) => void;
		onmenu: (request: FileMenuRequest) => void;
	}

	let { files, selected, progress, matchOf, onselect, onmenu }: Props = $props();

	const percent = $derived(
		progress && progress.lines > 0 ? Math.round((progress.validatedLines / progress.lines) * 100) : 0
	);
	const nf = new Intl.NumberFormat();

	function split(sourceFile: string): { name: string; dir: string } {
		const index = sourceFile.lastIndexOf('/');
		return index < 0
			? { name: sourceFile, dir: '' }
			: { name: sourceFile.slice(index + 1), dir: sourceFile.slice(0, index) };
	}

	function label(file: FileEntry, match: number | null): string {
		const { name, dir } = split(file.sourceFile);
		const base = $t('review.file_aria', {
			name,
			dir: dir || $t('review.file_root'),
			ok: file.validated,
			total: file.total
		});
		return match === null ? base : `${base}, ${$t('review.file_matches', { n: match })}`;
	}

	function menuFromKey(event: KeyboardEvent, file: FileEntry) {
		if (!matches('file_menu', event) && !(event.key === 'F10' && event.shiftKey)) return;
		event.preventDefault();
		const anchor = event.currentTarget as HTMLElement;
		const box = anchor.getBoundingClientRect();
		onmenu({ file, x: box.left, y: box.bottom, anchor });
	}

	function menuFromPointer(event: MouseEvent, file: FileEntry) {
		event.preventDefault();
		const anchor = event.currentTarget as HTMLElement;
		// A keyboard-opened contextmenu event carries no pointer position.
		const fromKeyboard = event.clientX === 0 && event.clientY === 0;
		onmenu({
			file,
			x: event.clientX,
			y: event.clientY,
			anchor: fromKeyboard ? anchor : null
		});
	}
</script>

<aside id="fichiers" aria-labelledby="h-files" tabindex="-1">
	<div class="head">
		<h2 id="h-files" class="cap">{$t('review.files_panel_title')}</h2>
		{#if progress}
			<label for="prog-project" class="progress-label">
				<span>{$t('review.project_validated')}</span>
				<span class="mono">{percent} %</span>
			</label>
			<progress
				id="prog-project"
				class="ok"
				value={progress.validatedLines}
				max={Math.max(1, progress.lines)}
			></progress>
			<p class="progress-count">
				{$t('review.progress_lines', {
					done: nf.format(progress.validatedLines),
					total: nf.format(progress.lines)
				})}
			</p>
		{/if}
	</div>
	<ul>
		{#each files as file (file.sourceFile)}
			{@const { name, dir } = split(file.sourceFile)}
			{@const match = matchOf(file)}
			<li>
				<button
					type="button"
					class="file"
					class:dim={match === 0}
					aria-current={file.sourceFile === selected ? 'true' : undefined}
					aria-label={label(file, match)}
					title={file.sourceFile}
					onclick={() => onselect(file.sourceFile)}
					oncontextmenu={(e) => menuFromPointer(e, file)}
					onkeydown={(e) => menuFromKey(e, file)}
				>
					<span class="fn">{name}</span>
					<span class="mono count">{file.validated}/{file.total}</span>
					<span class="dir">{dir || $t('review.file_root')}</span>
					<span class="badges mono">
						{#if match !== null}
							<span class="match" aria-hidden="true">{match}</span>
						{/if}
						{#if file.aiSuggested > 0}<span aria-hidden="true" title={$t('status.ai_suggested')}
								>{$t('review.ai_suggested_badge', { n: file.aiSuggested })}</span
							>{/if}
						{#if file.imported > 0}<span aria-hidden="true" title={$t('status.imported')}
								>{$t('review.imported_badge', { n: file.imported })}</span
							>{/if}
						{#if file.draft > 0}<span aria-hidden="true" title={$t('status.draft')}
								>{$t('review.draft_badge', { n: file.draft })}</span
							>{/if}
					</span>
				</button>
			</li>
		{/each}
	</ul>
</aside>

<style>
	aside {
		width: 256px;
		flex: none;
		border-right: 1px solid var(--line);
		background: var(--bg);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	aside:focus {
		outline: none;
	}

	.head {
		padding: 20px 18px 14px;
	}

	.head .cap {
		margin: 0 0 14px;
	}

	.progress-label {
		display: flex;
		justify-content: space-between;
		font-size: 13px;
		color: var(--ink2);
		margin-bottom: 7px;
	}

	progress {
		height: 4px;
	}

	.progress-count {
		margin: 7px 0 0;
		font-size: 12px;
		color: var(--ink3);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 4px 8px 16px;
		overflow: auto;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.file {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 1px 10px;
		width: 100%;
		text-align: left;
		padding: 8px 10px;
		border: 0;
		background: transparent;
		border-radius: var(--r-md);
		color: var(--ink);
	}

	.file:hover {
		background: var(--sunken);
	}

	.file[aria-current='true'] {
		background: var(--accWeak);
	}

	.file[aria-current='true'] .fn {
		color: var(--acc7);
		font-weight: 600;
	}

	.file.dim {
		opacity: 0.55;
	}

	.fn {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 13.5px;
	}

	.count {
		font-size: 12px;
		color: var(--ink3);
	}

	.dir {
		grid-column: 1 / -1;
		font-size: 12px;
		color: var(--ink3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.badges {
		grid-column: 1 / -1;
		display: flex;
		gap: 6px;
		font-size: 11px;
		color: var(--ink3);
		white-space: nowrap;
	}

	.badges:empty {
		display: none;
	}

	.match {
		color: var(--acc7);
		font-weight: 500;
	}
</style>
