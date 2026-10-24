// Typed wrappers around the Tauri commands in `src-tauri/src/commands/`.
// One function per command; keeps every `invoke()` call and its argument
// shape in a single place instead of scattered through the routes.

import { invoke } from '@tauri-apps/api/core';

export interface ProjectEntry {
	name: string;
	path: string;
	ready: boolean;
}

export interface ProjectInfo {
	path: string;
	gameName: string;
	sourceLanguage: string;
	targetLanguage: string;
	byStatus: Record<string, number>;
}

export interface FileEntry {
	sourceFile: string;
	total: number;
	validated: number;
	aiSuggested: number;
	draft: number;
	imported: number;
}

export interface UnitPayload {
	blockId: string;
	sourceFile: string;
	sourceLine: number;
	speaker: string | null;
	sourceText: string;
	translatedText: string;
	status: string;
	needsReview: boolean;
	note: string | null;
}

export interface ListUnitsArgs {
	sourceFile: string;
	status?: string | null;
	search?: string;
	speaker?: string | null;
	needsReview?: boolean;
	page?: number;
	pageSize?: number;
}

export interface ListUnitsResult {
	units: UnitPayload[];
	total: number;
	page: number;
	pageSize: number;
}

export interface QualityIssuePayload {
	kind: string;
	detail: string;
}

export interface ValidateResult {
	unit: UnitPayload | null;
	blockingIssues: QualityIssuePayload[];
	warnings: QualityIssuePayload[];
}

export interface CharacterEntry {
	variable: string;
	displayName: string;
	notes: string | null;
}

export interface SettingsPayload {
	locale: string | null;
	theme: string | null;
	defaultProvider: string | null;
	deeplApiKeySet: boolean;
	ollamaEndpoint: string | null;
	ollamaModel: string | null;
	ollamaBatchSize: string | null;
	libretranslateUrl: string | null;
	libretranslateApiKeySet: boolean;
	verboseLogging: boolean;
	sdkPath: string | null;
	availableProviders: string[];
	availableLlmProviders: string[];
}

export interface TestConnectionResult {
	ok: boolean;
	detail: string | null;
	models: string[];
}

export interface StartJobArgs {
	providerId: string;
	scope: 'project' | 'file';
	sourceFile?: string | null;
}

export type JobEventPayload =
	| {
			kind: 'progress';
			total: number;
			done: number;
			failed: number;
			running: boolean;
			finished: boolean;
			error: string | null;
	  }
	| { kind: 'chunkPersisted' }
	| { kind: 'event'; message: string };

export interface LanguageEntry {
	code: string;
	label: string;
}

export interface GameInspection {
	valid: boolean;
	gameName: string;
	needsSdk: boolean;
	hasExistingTl: boolean;
	hasDatabase: boolean;
	existingLanguages: string[];
}

export type ExtractMode = 'keep' | 'update' | 'reset';

export type ExtractionStage = 'archiving' | 'unpacking' | 'running' | 'parsing' | 'syncing';

export interface ExtractionReport {
	units: number;
	moved: number;
	obsolete: number;
	discardedSources: string[];
	repaired: number;
}

export interface ExtractionOutcome {
	project: ProjectInfo;
	report: ExtractionReport;
}

/** What a failed extraction carries; `code` selects the localized message. */
export interface ExtractionFailure {
	code: string;
	message: string;
	detail: string | null;
	params: Record<string, string>;
}

export const api = {
	listRecentProjects: () => invoke<ProjectEntry[]>('list_recent_projects'),
	openProject: (path: string) => invoke<ProjectInfo>('open_project', { path }),
	currentProject: () => invoke<ProjectInfo | null>('current_project'),
	listLanguages: () => invoke<LanguageEntry[]>('list_languages'),
	inspectGame: (path: string, targetLanguage: string) =>
		invoke<GameInspection>('inspect_game', { path, targetLanguage }),
	extractProject: (args: {
		path: string;
		sourceLanguage: string;
		targetLanguage: string;
		mode: ExtractMode;
	}) => invoke<ExtractionOutcome>('extract_project', args),

	listFiles: () => invoke<FileEntry[]>('list_files'),
	listUnits: (args: ListUnitsArgs) => invoke<ListUnitsResult>('list_units', { args }),
	saveDraft: (blockId: string, translatedText: string) =>
		invoke<UnitPayload>('save_draft', { blockId, translatedText }),
	validateUnit: (blockId: string, translatedText: string) =>
		invoke<ValidateResult>('validate_unit', { blockId, translatedText }),
	setNeedsReview: (blockId: string, needsReview: boolean) =>
		invoke<UnitPayload>('set_needs_review', { blockId, needsReview }),
	setNote: (blockId: string, note: string) => invoke<UnitPayload>('set_note', { blockId, note }),

	startTranslationJob: (args: StartJobArgs) => invoke<void>('start_translation_job', { args }),
	cancelTranslationJob: () => invoke<void>('cancel_translation_job'),
	isTranslationJobRunning: () => invoke<boolean>('is_translation_job_running'),

	getSettings: () => invoke<SettingsPayload>('get_settings'),
	setSetting: (key: string, value: string | null) => invoke<void>('set_setting', { key, value }),
	testDeeplConnection: (apiKey: string) =>
		invoke<TestConnectionResult>('test_deepl_connection', { apiKey }),
	testOllamaConnection: (endpoint: string) =>
		invoke<TestConnectionResult>('test_ollama_connection', { endpoint }),
	testLibretranslateConnection: (url: string, apiKey: string | null) =>
		invoke<TestConnectionResult>('test_libretranslate_connection', { url, apiKey }),

	listCharacters: () => invoke<CharacterEntry[]>('list_characters'),
	upsertCharacter: (variable: string, displayName: string, notes: string | null) =>
		invoke<CharacterEntry[]>('upsert_character', { variable, displayName, notes }),
	deleteCharacter: (variable: string) =>
		invoke<CharacterEntry[]>('delete_character', { variable }),

	getUniverseSummary: () => invoke<string | null>('get_universe_summary'),
	setUniverseSummary: (summary: string) => invoke<void>('set_universe_summary', { summary }),

	saveProject: () => invoke<void>('save_project'),
	exportProject: (outputPath: string) => invoke<void>('export_project', { outputPath })
};
