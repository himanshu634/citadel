/** Shapes the UI renders. They mirror the brain's graph labels (apps/backend/brain/canonical.py). */

export type NodeType = 'person' | 'team' | 'system' | 'work-item' | 'change' | 'document';

export const NODE_LABELS: Record<NodeType, string> = {
	person: 'Person',
	team: 'Team',
	system: 'System',
	'work-item': 'Work item',
	change: 'Change',
	document: 'Document'
};

export const NODE_PLURALS: Record<NodeType, string> = {
	person: 'People',
	team: 'Teams',
	system: 'Systems',
	'work-item': 'Work items',
	change: 'Changes',
	document: 'Documents'
};

export type WorkItemKind = 'pull_request' | 'issue' | 'thread';
export type WorkItemState = 'open' | 'merged' | 'closed';

export interface GraphNodeRef {
	uid: string;
	type: NodeType;
	label: string;
}

export interface PathStep {
	node: GraphNodeRef;
	/** Relationship to the next step, e.g. AUTHORED. Omitted on the last step. */
	edge?: string;
}

export interface Source {
	uid: string;
	title: string;
	meta: string;
	url?: string;
}

export interface CitedAnswer {
	question: string;
	/** Answer text split into runs; a run with `cite` renders citation chips after it. */
	parts: { text: string; cite?: number[] }[];
	path: PathStep[];
	sources: Source[];
}

export interface WorkItem {
	uid: string;
	kind: WorkItemKind;
	number?: number;
	title: string;
	state: WorkItemState;
	author: string;
	date: string;
	system?: string;
}

export interface Person {
	login: string;
	name: string;
	team: string;
	prs: number;
	reviews: number;
}

export interface SystemActivity {
	name: string;
	team: string;
	changes: number;
}

export interface GraphCount {
	type: NodeType;
	count: number;
}

export interface MenuItem {
	value: string;
	label: string;
	hint?: string;
	selected?: boolean;
}
