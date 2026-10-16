import { describe, expect, test } from 'vitest';
import { addTags, hasSeparator, inOpenBrace, removeTag } from './tags';

describe('addTags', () => {
	test('adds one trimmed tag', () => {
		expect(addTags([], '  src/**  ')).toEqual(['src/**']);
	});

	test('keeps the existing order and appends', () => {
		expect(addTags(['a'], 'b')).toEqual(['a', 'b']);
	});

	test('ignores empty and whitespace-only input', () => {
		expect(addTags(['a'], '')).toEqual(['a']);
		expect(addTags(['a'], '   ')).toEqual(['a']);
		expect(addTags(['a'], ' , ,, ')).toEqual(['a']);
	});

	test('ignores a tag that is already there', () => {
		expect(addTags(['a', 'b'], 'a')).toEqual(['a', 'b']);
		expect(addTags(['a'], ' a ')).toEqual(['a']);
	});

	test('a paste of "a, b" adds both', () => {
		expect(addTags([], 'a, b')).toEqual(['a', 'b']);
	});

	test('a paste with repeats and a trailing comma adds each once', () => {
		expect(addTags(['x'], 'a, b,a, x, ')).toEqual(['x', 'a', 'b']);
	});

	test('a paste split over lines adds each line', () => {
		expect(addTags([], 'a\nb\r\nc')).toEqual(['a', 'b', 'c']);
	});

	test('tags are case sensitive (paths and logins are)', () => {
		expect(addTags(['Docs'], 'docs')).toEqual(['Docs', 'docs']);
	});

	test('returns the same array when nothing was added', () => {
		const values = ['a'];
		expect(addTags(values, 'a')).toBe(values);
		expect(addTags(values, '')).toBe(values);
	});

	test('does not change the array it was given', () => {
		const values = ['a'];
		addTags(values, 'b');
		expect(values).toEqual(['a']);
	});
});

describe('removeTag', () => {
	test('removes the tag', () => {
		expect(removeTag(['a', 'b', 'c'], 'b')).toEqual(['a', 'c']);
	});

	test('an unknown tag changes nothing', () => {
		const values = ['a'];
		expect(removeTag(values, 'z')).toBe(values);
	});
});

describe('hasSeparator', () => {
	test('is true when the text holds a comma or a line break', () => {
		expect(hasSeparator('a,')).toBe(true);
		expect(hasSeparator('a, b')).toBe(true);
		expect(hasSeparator('a\nb')).toBe(true);
	});

	test('is false for plain text', () => {
		expect(hasSeparator('a b')).toBe(false);
		expect(hasSeparator('')).toBe(false);
	});
});

describe('brace globs (a comma inside {} is part of the glob)', () => {
	test('a brace glob stays one tag', () => {
		expect(addTags([], '**/*.{ts,tsx}')).toEqual(['**/*.{ts,tsx}']);
	});

	test('a paste mixing brace globs and plain tags splits only outside braces', () => {
		expect(addTags([], 'a, **/*.{ts,tsx}, b')).toEqual(['a', '**/*.{ts,tsx}', 'b']);
	});

	test('nested braces count', () => {
		expect(addTags([], 'x/{a,{b,c}}/y, z')).toEqual(['x/{a,{b,c}}/y', 'z']);
	});

	test('a line break splits even inside braces', () => {
		expect(addTags([], '{a,\nb}')).toEqual(['{a,', 'b}']);
	});

	test('an unclosed brace keeps its comma while typing', () => {
		expect(hasSeparator('**/*.{ts,')).toBe(false);
		expect(hasSeparator('**/*.{ts,tsx},')).toBe(true);
		expect(inOpenBrace('**/*.{ts,')).toBe(true);
		expect(inOpenBrace('**/*.{ts,tsx}')).toBe(false);
		expect(inOpenBrace('}{')).toBe(true);
		expect(inOpenBrace('')).toBe(false);
	});

	test('a stray closing brace does not hide the next comma', () => {
		expect(addTags([], 'a}, b')).toEqual(['a}', 'b']);
	});
});
