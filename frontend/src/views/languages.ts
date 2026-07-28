/**
 * The syntax-highlighting language set.
 *
 * highlight.js's default "common" bundle is ~37 languages and cost +53 kB
 * gzipped on the critical path — every message renders through Markdown, so
 * that is not a lazy cost. These are the languages that actually show up in
 * this platform's answers; anything else still renders, just unhighlighted.
 *
 * Aliases (js, ts, py, sh, yml…) come free — highlight.js registers the ones
 * each language definition declares.
 */
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

export const languages = {
  bash,
  css,
  diff,
  dockerfile,
  go,
  java,
  javascript,
  json,
  markdown,
  python,
  rust,
  sql,
  typescript,
  xml, // also covers html
  yaml,
};
