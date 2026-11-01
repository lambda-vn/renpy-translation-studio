<script lang="ts">
	// App-wide settings, opened by the header gear (`settingsOpen`): interface
	// language, theme, verbose log, Ren'Py SDK, translation memory, and the way
	// to the providers screen. Each change is saved as soon as it is made.
	import { goto } from '$app/navigation';
	import { api, type MemoryPair } from '$lib/api';
	import { confirmDialog } from '$lib/confirm';
	import { locale, t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { languageName } from '$lib/languages';
	import { ROUTES } from '$lib/navigation';
	import { jobRunning, settingsOpen } from '$lib/stores';
	import { parseTheme, setTheme, themePreference, THEME_PREFERENCES } from '$lib/theme';
	import { toast } from '$lib/toast';
	import Dialog from './Dialog.svelte';
	import SdkField from './SdkField.svelte';
	import Select from './Select.svelte';

	const LOCALES = [
		{ code: 'fr', name: 'Français' },
		{ code: 'en', name: 'English' }
	];

	let sdkPath = $state('');
	let verbose = $state(false);
	let memory = $state<MemoryPair[]>([]);
	let error = $state('');

	$effect(() => {
		if ($settingsOpen) void load();
	});

	async function load() {
		error = '';
		try {
			const settings = await api.getSettings();
			sdkPath = settings.sdkPath ?? '';
			verbose = settings.verboseLogging;
			setTheme(settings.theme);
			memory = await api.memoryStats();
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function changeLocale(value: string) {
		$locale = value;
		await persist('locale', value);
	}

	async function changeTheme(choice: string) {
		const value = parseTheme(choice);
		setTheme(value);
		await persist('theme', value);
	}

	async function changeVerbose() {
		await persist('verbose_logging', verbose ? '1' : null);
	}

	async function revealLog() {
		try {
			await api.revealLog();
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function persist(key: string, value: string | null) {
		try {
			await api.setSetting(key, value);
			error = '';
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function forget(pair: MemoryPair) {
		const source = languageName(pair.sourceLanguage, $t);
		const target = languageName(pair.targetLanguage, $t);
		const confirmed = await confirmDialog({
			title: $t('settings.memory_forget_title'),
			message: $t('settings.memory_forget_message', { source, target, n: pair.entries }),
			confirmLabel: $t('settings.memory_forget'),
			danger: true
		});
		if (!confirmed) return;
		try {
			await api.forgetMemory(pair.sourceLanguage, pair.targetLanguage);
			memory = await api.memoryStats();
			toast.success($t('settings.memory_forgotten', { source, target }));
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function openProviders() {
		$settingsOpen = false;
		await goto(ROUTES.providers);
	}
</script>

<Dialog bind:open={$settingsOpen} title={$t('settings.title')}>
	{#if error}
		<p class="notice err" role="alert">{error}</p>
	{/if}

	<div>
		<label class="lbl" for="set-lang">{$t('settings.language_label')}</label>
		<Select
			id="set-lang"
			label={$t('settings.language_label')}
			value={$locale}
			options={LOCALES.map((option) => ({ value: option.code, label: option.name }))}
			onchange={changeLocale}
		/>
	</div>

	<div>
		<label class="lbl" for="set-theme">{$t('settings.theme_label')}</label>
		<Select
			id="set-theme"
			label={$t('settings.theme_label')}
			value={$themePreference}
			options={THEME_PREFERENCES.map((value) => ({ value, label: $t(`themes.${value}`) }))}
			onchange={changeTheme}
		/>
	</div>

	<div class="switch-row">
		<div class="grow">
			<label for="set-log" class="switch-label">{$t('provider_config.verbose_logging_label')}</label>
			<span class="help">{$t('settings.verbose_hint')}</span>
			<button type="button" class="btn ghost log-btn" onclick={revealLog}>
				{$t('settings.open_log')}
			</button>
		</div>
		<span class="sw">
			<input
				id="set-log"
				type="checkbox"
				checked={verbose}
				onchange={(event) => {
					verbose = event.currentTarget.checked;
					void changeVerbose();
				}}
			/>
			<span></span>
		</span>
	</div>

	<SdkField
		id="set-sdk"
		label={$t('settings.sdk_label')}
		placeholder={$t('settings.sdk_none')}
		help={$t('settings.sdk_hint')}
		browseLabel="{$t('settings.sdk_browse')}…"
		clearLabel={$t('settings.clear')}
		bind:value={sdkPath}
		onchange={(path) => api.setSetting('sdk_path', path)}
	/>

	<div>
		<p class="lbl">{$t('settings.memory_label')}</p>
		<p class="help top">{$t('settings.memory_hint')}</p>
		{#if memory.length === 0}
			<p class="help">{$t('settings.memory_empty')}</p>
		{:else}
			<ul class="memory">
				{#each memory as pair (`${pair.sourceLanguage}>${pair.targetLanguage}`)}
					{@const source = languageName(pair.sourceLanguage, $t)}
					{@const target = languageName(pair.targetLanguage, $t)}
					<li>
						<span class="grow">{$t('settings.memory_pair', { source, target })}</span>
						<span class="mono count">{$t('settings.memory_entries', { n: pair.entries })}</span>
						<button
							type="button"
							class="btn ghost icon"
							aria-label="{$t('settings.memory_forget')} : {source} → {target}"
							title={$t('settings.memory_forget')}
							onclick={() => forget(pair)}
						>
							<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" /></svg>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<div>
		<p class="lbl">{$t('provider_config.title')}</p>
		<button type="button" class="btn" disabled={$jobRunning} onclick={openProviders}>
			{$t('provider_config.open_settings')}
		</button>
	</div>

	{#snippet actions()}
		<button type="button" class="btn primary" onclick={() => ($settingsOpen = false)}>
			{$t('settings.close')}
		</button>
	{/snippet}
</Dialog>

<style>
	.grow {
		flex: 1;
		min-width: 0;
	}
	.switch-row {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}
	.switch-label {
		display: block;
		font-size: 13px;
		font-weight: 500;
	}
	.log-btn {
		margin-top: 6px;
	}
	.help.top {
		margin: 0 0 8px;
	}
	.memory {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
	}
	.memory li {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 2px 0;
		border-bottom: 1px solid var(--line);
		font-size: 13px;
	}
	.memory li:last-child {
		border-bottom: 0;
	}
	.count {
		font-size: 12px;
		color: var(--ink2);
	}
</style>
