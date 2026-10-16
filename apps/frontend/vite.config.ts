import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// Vite runs this file in Node; the app has no Node types, and this is all it reads.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// `make api` serves the backend here (API_PORT moves it); the UI always calls it through /api.
		proxy: { '/api': `http://127.0.0.1:${process.env.API_PORT ?? 8000}` }
	},
	test: {
		include: ['src/**/*.test.ts']
	}
});
