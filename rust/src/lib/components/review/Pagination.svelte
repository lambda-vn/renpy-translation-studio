<script lang="ts">
	// Footer: the range shown, the page buttons and the shortcuts opener.
	import Kbd from '$lib/components/Kbd.svelte';
	import { t } from '$lib/i18n';

	interface Props {
		page: number;
		total: number;
		pageSize: number;
		onpage: (page: number) => void;
		onhelp: () => void;
	}

	let { page, total, pageSize, onpage, onhelp }: Props = $props();

	const pageCount = $derived(Math.max(1, Math.ceil(total / pageSize)));
	const from = $derived(total === 0 ? 0 : page * pageSize + 1);
	const to = $derived(Math.min(total, (page + 1) * pageSize));

	/** First, last and the neighbours of the current page; null is a gap. */
	const items = $derived.by((): (number | null)[] => {
		const wanted = new Set([0, pageCount - 1, page - 1, page, page + 1]);
		const pages = [...wanted].filter((p) => p >= 0 && p < pageCount).sort((a, b) => a - b);
		const result: (number | null)[] = [];
		pages.forEach((p, index) => {
			if (index > 0 && p - pages[index - 1] > 1) result.push(null);
			result.push(p);
		});
		return result;
	});
</script>

<footer>
	<p class="range">
		{$t('review.lines_range', { from, to, total })}
	</p>
	{#if pageCount > 1}
		<nav aria-label={$t('review.pagination_label')}>
			<ul>
				<li>
					<button type="button" class="btn ghost" disabled={page === 0} onclick={() => onpage(page - 1)}>
						{$t('review.page_prev')}
					</button>
				</li>
				{#each items as item, index (index)}
					<li>
						{#if item === null}
							<span class="gap" aria-hidden="true">…</span>
						{:else}
							<button
								type="button"
								class="btn ghost num"
								aria-current={item === page ? 'page' : undefined}
								onclick={() => onpage(item)}
							>
								<span class="sr">{$t('review.page_word')} </span>{item + 1}
							</button>
						{/if}
					</li>
				{/each}
				<li>
					<button
						type="button"
						class="btn ghost"
						disabled={page >= pageCount - 1}
						onclick={() => onpage(page + 1)}
					>
						{$t('review.page_next')}
					</button>
				</li>
			</ul>
		</nav>
	{/if}
	<span class="spacer"></span>
	<button type="button" class="btn ghost" onclick={onhelp}>
		<Kbd keys="F1" />
		{$t('review.shortcuts_button')}
	</button>
</footer>

<style>
	footer {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px 16px;
		min-height: 52px;
		padding: 8px 28px;
		border-top: 1px solid var(--line);
		font-size: 13px;
		color: var(--ink2);
		flex: none;
	}

	.range {
		margin: 0;
		font-family: var(--font-mono);
		font-size: 12.5px;
	}

	ul {
		list-style: none;
		display: flex;
		align-items: center;
		gap: 2px;
		margin: 0;
		padding: 0;
	}

	.num {
		width: 34px;
		padding: 0;
	}

	.num[aria-current='page'] {
		background: var(--accWeak);
		color: var(--acc7);
		font-weight: 600;
	}

	.gap {
		display: inline-block;
		width: 24px;
		text-align: center;
		color: var(--ink3);
	}

	.spacer {
		flex: 1;
	}
</style>
