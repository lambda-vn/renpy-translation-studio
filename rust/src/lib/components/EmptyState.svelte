<script lang="ts">
	// Centered "nothing here" block: icon, heading, one sentence, optional buttons.
	//
	//   <EmptyState title="No matching line" description="...">
	//     <button class="btn">Clear the search</button>
	//   </EmptyState>
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		description?: string;
		/** Heading level, to fit the page outline. */
		level?: 2 | 3;
		/** Replaces the default magnifier. Decorative: it is hidden from assistive tech. */
		icon?: Snippet;
		/** Buttons or links, laid out in a row. */
		children?: Snippet;
	}

	let { title, description, level = 2, icon, children }: Props = $props();
</script>

<div class="empty">
	<div class="icon" aria-hidden="true">
		{#if icon}
			{@render icon()}
		{:else}
			<svg
				width="40"
				height="40"
				viewBox="0 0 40 40"
				fill="none"
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
			>
				<circle cx="17" cy="17" r="10" />
				<path d="M25 25l8 8M13 17h8" />
			</svg>
		{/if}
	</div>
	<svelte:element this={`h${level}`} class="title">{title}</svelte:element>
	{#if description}
		<p class="description">{description}</p>
	{/if}
	{#if children}
		<div class="actions">
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		max-width: 420px;
		margin: auto;
		padding: 40px 28px;
		text-align: center;
	}

	.icon {
		color: var(--ink3);
		display: flex;
	}

	.title {
		margin: 0;
		font-size: 16px;
		font-weight: 700;
	}

	.description {
		margin: 0;
		color: var(--ink2);
		font-size: 13.5px;
		line-height: 1.55;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 8px;
		margin-top: 6px;
	}
</style>
