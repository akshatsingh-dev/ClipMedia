export type Clip = {
  video_id: string;
  t_start: number;
  t_end: number;
  why: string;
  credit_url: string;
  video_title: string;
  channel: string;
  channel_url: string;
  thumbnail: string;
};

export type Chapter = {
  title: string;
  intro_text: string;
  clips: Clip[];
};

export type Group = {
  label: string;
  clips: Clip[];
};

export type Page = {
  slug: string;
  query: string;
  title: string;
  subtitle: string;
  mode: "learn" | "entertain";
  timestamps_verified: boolean;
  source_note: string;
  chapters?: Chapter[];
  groups?: Group[];
};

export type IndexEntry = {
  slug: string;
  title: string;
  subtitle: string;
  mode: "learn" | "entertain";
  query: string;
  clip_count: number;
};
