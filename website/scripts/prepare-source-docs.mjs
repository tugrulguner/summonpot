import { mkdir, readFile, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const website = dirname(dirname(fileURLToPath(import.meta.url)));
const repository = resolve(website, "..");
const docs = join(website, "src/content/docs/source");
const gitHub = "https://github.com/tugrulguner/summonpot";
const sha = process.env.GITHUB_SHA ?? process.env.DOCS_SOURCE_SHA ?? execFileSync("git", ["-C", repository, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();

if (!/^(?:[0-9a-f]{40}|[A-Za-z0-9._/-]+)$/.test(sha) || sha.includes("..")) {
  throw new Error(`Invalid documentation source revision: ${sha}`);
}

for (const name of ["README.md", "ROADMAP.md"]) {
  const original = await readFile(join(repository, name), "utf8");
  const source = original.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "");
  const markdown = source.replace(/(!?)\[([^\]]*)\]\(([^)]+)\)/g, (link, image, label, target) => {
    if (/^(?:https?:|mailto:|#|\/)/i.test(target)) return link;
    const url = `${gitHub}/${image ? "raw" : "blob"}/${sha}/${target}`;
    return `${image}[${label}](${url})`;
  }).replace(/\b(src|href)=(['"])(?!https?:|mailto:|#|\/)([^'"]+)\2/gi, (attribute, name, quote, target) => {
    const url = `${gitHub}/${name.toLowerCase() === "src" ? "raw" : "blob"}/${sha}/${target}`;
    return `${name}=${quote}${url}${quote}`;
  });
  const title = name === "README.md" ? "Project README" : "Project roadmap";
  const label = name === "README.md" ? "README (current source)" : "Roadmap (planned work)";
  const description = name === "README.md"
    ? "The current, source-controlled Summonpot project overview and documentation."
    : "Source-controlled Summonpot plans. Roadmap items are planned work, not claims of shipped functionality.";
  const generated = `---\ntitle: ${title}\ndescription: ${description}\nsidebar:\n  label: ${label}\n---\n\n> Generated from [${name}](${gitHub}/blob/${sha}/${name}), a repository documentation snapshot at commit [${sha}](${gitHub}/tree/${sha}). Roadmap items are planned work, not claims of shipped features.\n\n${markdown}`;
  const route = join(docs, name === "README.md" ? "readme.md" : "roadmap.md");
  await mkdir(docs, { recursive: true });
  await writeFile(route, generated);
  console.log(`Generated ${route.split(sep).slice(-2).join("/")} from ${name} (${sha})`);
}
