import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const newsItemSchema = z.object({
  type: z.enum(['one_line', 'short', 'explainer', 'alert_chip', 'lead', 'compact_brief', 'closing_brief']),
  title: z.string(),
  summary: z.string().optional(),
  brief: z.string().optional(),
  why_it_matters: z.string().optional(),
  scope: z.string().optional(),
});

const sectionSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional(),
  scope_label: z.string().optional(),
  items: z.array(newsItemSchema),
});

const editions = defineCollection({
  loader: glob({ base: './src/content/editions', pattern: '**/*.{md,mdx}' }),
  schema: z.object({
    title: z.string(),
    subtitle: z.string().optional(),
    date: z.string(),
    readTime: z.number(),
    editionKey: z.string(),
    sections: z.array(sectionSchema),
  }),
});

export const collections = { editions };
