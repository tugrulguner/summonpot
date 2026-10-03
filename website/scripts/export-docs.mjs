import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const website = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceRoot = join(website, "src/content/docs");
const distRoot = join(website, "dist");
const routes = [
  ["tasks/direct-execution.mdx", "build/direct-execution.md", "build/direct-execution/index.html"],
  ["tasks/agent-choice.mdx", "build/agent-choice.md", "build/agent-choice/index.html"],
  ["reference/operations.mdx", "reference/operations.md", "reference/operations/index.html"],
  ["internals/execution.mdx", "internals/execution.md", "internals/execution/index.html"],
  ["guides/operations.mdx", "guides/operations.md", "guides/operations/index.html"],
];
const failures = [];
for (const [sourceRelative, exportRelative, htmlRelative] of routes) {
  const source = await readFile(join(sourceRoot, sourceRelative), "utf8");
  const markdown = source
    .replace(/^---\n[\s\S]*?\n---\n/, "")
    .replace(/^import \{ LinkButton \} from '@astrojs\/starlight\/components';\n\n/m, "")
    .replace(/^<LinkButton[^\n]*\n/m, "");
  const exportedPath = join(distRoot, exportRelative);
  await mkdir(dirname(exportedPath), { recursive: true });
  await writeFile(exportedPath, markdown);
  const emitted = await readFile(exportedPath, "utf8");
  if (emitted !== markdown) failures.push(`${exportRelative}: export differs from canonical source`);
  const html = await readFile(join(distRoot, htmlRelative), "utf8");
  for (const heading of markdown.matchAll(/^#{1,6} (.+)$/gm)) {
    const slug = heading[1].toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").trim().replace(/\s+/g, "-");
    if (!html.includes(`id="${slug}"`)) failures.push(`${htmlRelative}: missing heading anchor #${slug}`);
  }
  const sitePath = `/${htmlRelative.replace(/index\.html$/, "")}`;
  const links = [...markdown.matchAll(/\]\(([^)]+)\)/g)].map((match) => match[1]);
  for (const link of links) {
    if (link.startsWith("#") && !html.includes(`id="${link.slice(1)}"`)) failures.push(`${sitePath}: missing local fragment ${link}`);
    if (/^\/(build|reference|internals|guides)\//.test(link)) {
      const target = link.endsWith(".md") ? link.slice(1) : `${link.slice(1)}index.html`;
      try { await readFile(join(distRoot, target)); } catch { failures.push(`${sitePath}: missing linked route ${link}`); }
    }
  }
  console.log(`Exported and checked ${sourceRelative} -> /${exportRelative}`);
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`Verified ${routes.length} canonical Markdown exports, HTML routes, anchors, and local guide links.`);
}
