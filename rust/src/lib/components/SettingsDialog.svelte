<script lang="ts">
	// App-wide settings, opened by the header gear (`settingsOpen`): interface
	// language, theme, verbose log, Ren'Py SDK, translation memory, and the way
	// to the providers screen. Each change is saved as soon as it is made.
	import { goto } from '$app/navigation';
	import { open as pickPath } from '@tauri-apps/plugin-dialog';
	import { api, type MemoryPair } from '$lib/api';
	import { confirmDialog } from '$lib/confirm';
	import { locale, t } from '$lib/i18n';
	import { languageName } from '$lib/languages';
	import { ROUTES } from '$lib/navigation';
	import { jobRunning, settingsOpen } from '$lib/stores';
	import { parseTheme, setTheme, themePreference, THEME_PREFERENCES } from '$lib/theme';
	import { toast } from '$lib/toast';
	import Dialog from './Dialog.svelte';

	const LOCALES = [
		{ code: 'fr', name: 'Français' },
		{ code: 'en', name: 'English' }
	];

	let sdkPath = $state('');
	let sdkError = $state('');
	let verbose = $state(false);
	let memory = $state<MemoryPair[]>([]);
	let error = $state('');

	$effect(() => {
		if ($settingsOpen) void load();
	});

	async function load() {
		error = '';
		sdkError = '';
		try {
			const settings = await api.getSettings();
			sdkPath = settings.sdkPath ?? '';
			verbose = settings.verboseLogging;
			setTheme(settings.theme);
			memory = await api.memoryStats();
		} catch (e) {
			error = String(e);
		}
	}

	async function changeLocale(event: Event) {
		const value = (event.currentTarget as HTMLSelectElement).value;
		$locale = value;
		await persist('locale', value);
	}

	async function changeTheme(event: Event) {
		const value = parseTheme((event.currentTarget as HTMLSelectElement).value);
		setTheme(value);
		await persist('theme', value);
	}

	async function changeVerbose() {
		await persist('verbose_logging', verbose ? '1' : null);
	}

	async function persist(key: string, value: string | null) {
		try {
			await api.setSetting(key, value);
			error = '';
		} catch (e) {
			error = String(e);
		}
	}

	async function browseSdk() {
		const picked = await pickPath({
			filters: [{ name: "Ren'Py", extensions: ['exe', 'sh', 'py'] }]
		});
		if (typeof picked !== 'string') return;
		sdkError = '';
		let valid = false;
		try {
			valid = await api.validateSdkPath(picked);
		} catch {
			valid = false;
		}
		if (!valid) {
			sdkError = $t('onboarding.sdk_invalid');
			return;
		}
		sdkPath = picked;
		await persist('sdk_path', picked);
	}

	async function clearSdk() {
		sdkPath = '';
		sdkError = '';
		await persist('sdk_path', null);
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
			error = String(e);
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
		<select id="set-lang" value={$locale} onchange={changeLocale}>
			{#each LOCALES as option (option.code)}
				<option value={option.code}>{option.name}</option>
			{/each}
		</select>
	</div>

	<div>
		<label class="lbl" for="set-theme">{$t('settings.theme_label')}</label>
		<select id="set-theme" value={$themePreference} onchange={changeTheme}>
			{#each THEME_PREFERENCES as value (value)}
				<option {value}>{$t(`themes.${value}`)}</option>
			{/each}
		</select>
	</div>

	<div class="switch-row">
		<div class="grow">
			<label for="set-log" class="switch-label">{$t('provider_config.verbose_logging_label')}</label>
			<span class="help">{$t('settings.verbose_hint')}</span>
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

	<div>
		<label class="lbl" for="set-sdk">{$t('settings.sdk_label')}</label>
		<div class="row">
			<input
				id="set-sdk"
				class="mono"
				readonly
				value={sdkPath}
				placeholder={$t('settings.sdk_none')}
				aria-describedby="set-sdk-help"
			/>
			<button type="button" class="btn" onclick={browseSdk}>{$t('settings.sdk_browse')}…</button>
			{#if sdkPath}
				<button type="button" class="btn ghost" onclick={clearSdk}>{$t('settings.clear')}</button>
			{/if}
		</div>
		{#if sdkError}<p class="notice err sdk-err" role="alert">{sdkError}</p>{/if}
		<p class="help" id="set-sdk-help">{$t('settings.sdk_hint')}</p>
	</div>

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
	.row {
		display: flex;
		gap: 6px;
	}
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
	.help.top {
		margin: 0 0 8px;
	}
	.sdk-err {
		margin-top: 6px;
		padding: 8px 10px;
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
