import { describe, expect, test } from 'vitest';
import {
	NO_REFS,
	codeRef,
	codeUrl,
	fileUrl,
	labelRuns,
	numberUrl,
	refContext,
	refUrl,
	safeUrl,
	siteName,
	textRuns,
	uidUrl
} from './links';

const GH = 'https://github.com/o/r';

describe('safeUrl', () => {
	test('keeps http(s), drops everything else', () => {
		expect(safeUrl('https://github.com/o/r/pull/1')).toBe('https://github.com/o/r/pull/1');
		expect(safeUrl('http://example.com/x')).toBe('http://example.com/x');
		expect(safeUrl('javascript:alert(1)')).toBeNull();
		expect(safeUrl('data:text/html,hi')).toBeNull();
		expect(safeUrl('not a url')).toBeNull();
		expect(safeUrl(null)).toBeNull();
	});
});

describe('siteName', () => {
	test('names the sites the brain reads', () => {
		expect(siteName('https://github.com/o/r')).toBe('GitHub');
		expect(siteName('https://linear.app/x/issue/ENG-1')).toBe('Linear');
		expect(siteName('https://www.example.com/a')).toBe('example.com');
	});
});

describe('uidUrl', () => {
	test('makes github.com pages from GitHub uids', () => {
		expect(uidUrl('github:o/r:pr:12')).toBe(`${GH}/pull/12`);
		expect(uidUrl('github:o/r:issue:7')).toBe(`${GH}/issues/7`);
		expect(uidUrl('github:o/r:commit:abc123')).toBe(`${GH}/commit/abc123`);
		expect(uidUrl('github:o/r:doc:docs/a b.md')).toBe(`${GH}/blob/HEAD/docs/a%20b.md`);
	});
	test('guesses nothing for other sources', () => {
		expect(uidUrl('synthetic:pr:1')).toBeNull();
		expect(uidUrl('linear:ENG-1')).toBeNull();
		expect(uidUrl('person:alice')).toBeNull();
		expect(uidUrl('github:o/r:commit:not-a-sha')).toBeNull();
	});
	test('refUrl prefers the record url, if it is safe', () => {
		expect(refUrl('synthetic:pr:1', 'https://example.com/pull/1')).toBe('https://example.com/pull/1');
		expect(refUrl('github:o/r:pr:2', 'javascript:x')).toBe(`${GH}/pull/2`);
		expect(refUrl('synthetic:pr:1', null)).toBeNull();
	});
});

describe('fileUrl', () => {
	test('files, lines, ranges and folders on the default branch', () => {
		expect(fileUrl('o/r', 'src/a.py')).toBe(`${GH}/blob/HEAD/src/a.py`);
		expect(fileUrl('o/r', './src/a.py', 42)).toBe(`${GH}/blob/HEAD/src/a.py#L42`);
		expect(fileUrl('o/r', 'src/a.py', 4, 9)).toBe(`${GH}/blob/HEAD/src/a.py#L4-L9`);
		expect(fileUrl('o/r', 'docs/x.md', 3)).toBe(`${GH}/blob/HEAD/docs/x.md?plain=1#L3`);
		expect(fileUrl('o/r', 'src/graph/')).toBe(`${GH}/tree/HEAD/src/graph`);
	});
});

describe('codeRef', () => {
	test('reads paths the model writes', () => {
		expect(codeRef('src/auth/token.py')).toEqual({ file: 'src/auth/token.py' });
		expect(codeRef('token.py:42')).toEqual({ file: 'token.py', line: 42 });
		expect(codeRef('src/a.c:4-9')).toEqual({ file: 'src/a.c', line: 4, end: 9 });
		expect(codeRef('src/a.c#L4-L9')).toEqual({ file: 'src/a.c', line: 4, end: 9 });
		expect(codeRef('README.md')).toEqual({ file: 'README.md' });
		expect(codeRef('deploy/Dockerfile')).toEqual({ file: 'deploy/Dockerfile' });
		expect(codeRef('src/graph/')).toEqual({ file: 'src/graph/' });
	});
	test('leaves words, names, globs and urls alone', () => {
		for (const t of ['identity', 'token.verify', 'o/r', 'src/**', 'v1.2.3', 'https://x.io/a.py', '.py', 'graph/', 'a b.py'])
			expect(codeRef(t), t).toBeNull();
	});
});

describe('refContext', () => {
	const seen = [
		{ uid: 'github:o/r:pr:12', url: `${GH}/pull/12` },
		{ uid: 'github:o/r:doc:docs/auth.md', url: `${GH}/blob/main/docs/auth.md` },
		{ rows: [{ uid: 'synthetic:pr:3', number: 3, url: 'https://example.com/pull/3' }] }
	];
	test('collects numbers and documents from nested objects', () => {
		const ctx = refContext(seen);
		expect(ctx.numbers.get(12)).toBe(`${GH}/pull/12`);
		expect(ctx.numbers.get(3)).toBe('https://example.com/pull/3');
		expect(ctx.files.get('docs/auth.md')).toBe(`${GH}/blob/main/docs/auth.md`);
		expect(ctx.repo).toBe('o/r'); // the only repo the walk saw
	});
	test('a number two items share resolves to nothing', () => {
		const ctx = refContext([
			{ uid: 'github:o/r:pr:5', url: `${GH}/pull/5` },
			{ uid: 'github:o/s:issue:5', url: 'https://github.com/o/s/issues/5' }
		]);
		expect(ctx.numbers.get(5)).toBeNull();
		expect(ctx.repo).toBeNull();
		expect(numberUrl(5, ctx)).toBeNull();
	});
	test("the company's one repo wins; two repos give none", () => {
		expect(refContext([], ['o/r']).repo).toBe('o/r');
		expect(refContext(seen, ['a/b', 'c/d']).repo).toBeNull();
	});
});

describe('numberUrl and codeUrl', () => {
	const ctx = refContext([{ uid: 'synthetic:pr:3', number: 3, url: 'https://example.com/pull/3' }], ['o/r']);
	test('a number the walk saw, else an issue in the repo', () => {
		expect(numberUrl(3, ctx)).toBe('https://example.com/pull/3');
		expect(numberUrl(9, ctx)).toBe(`${GH}/issues/9`);
		expect(numberUrl(9, NO_REFS)).toBeNull();
		expect(numberUrl(9, NO_REFS, 'x/y')).toBe('https://github.com/x/y/issues/9');
	});
	test('a path: the document the walk saw, else the file', () => {
		const withDoc = refContext([{ uid: 'github:o/r:doc:docs/a.md', url: `${GH}/blob/main/docs/a.md` }]);
		expect(codeUrl({ file: 'docs/a.md' }, withDoc)).toBe(`${GH}/blob/main/docs/a.md`);
		expect(codeUrl({ file: 'docs/a.md', line: 2 }, withDoc)).toBe(`${GH}/blob/HEAD/docs/a.md?plain=1#L2`);
		expect(codeUrl({ file: 'src/a.py' }, NO_REFS)).toBeNull();
	});
});

describe('textRuns', () => {
	const ctx = refContext([], ['o/r']);
	test('links #n, owner/name#n and paths with a slash', () => {
		expect(textRuns('Fixed in #12 and x/y#3, see src/a.py:4.', ctx)).toEqual([
			{ text: 'Fixed in ' },
			{ text: '#12', href: `${GH}/issues/12` },
			{ text: ' and ' },
			{ text: 'x/y#3', href: 'https://github.com/x/y/issues/3' },
			{ text: ', see ' },
			{ text: 'src/a.py:4', href: `${GH}/blob/HEAD/src/a.py#L4` },
			{ text: '.' }
		]);
	});
	test('leaves entities, anchors, urls and words alone', () => {
		const text = 'a &#12; page#3 issue#4 and/or https://github.com/o/r/a.py token.py';
		expect(textRuns(text, ctx)).toEqual([{ text }]);
	});
	test('with no repo only named refs link', () => {
		expect(textRuns('#12 and x/y#3', NO_REFS)).toEqual([
			{ text: '#12 and ' },
			{ text: 'x/y#3', href: 'https://github.com/x/y/issues/3' }
		]);
	});
});

describe('labelRuns', () => {
	test('links each label once, skipping those with no url', () => {
		expect(
			labelRuns('Found how PR #10 and alice connect', [
				{ label: 'PR #10', href: `${GH}/pull/10` },
				{ label: 'alice', href: null }
			])
		).toEqual([{ text: 'Found how ' }, { text: 'PR #10', href: `${GH}/pull/10` }, { text: ' and alice connect' }]);
	});
});
