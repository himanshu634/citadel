import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// `make api` serves the backend here; the UI always calls it through /api.
		proxy: { '/api': 'http://127.0.0.1:8000' }
	},
	test: {
		include: ['src/**/*.test.ts']
	}
});
