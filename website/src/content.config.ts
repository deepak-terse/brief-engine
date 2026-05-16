import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const newsItemSchema = z.object({
  type: z.enum(['one_line', 'short', 'explainer']),
  title: z.string(),
  summary: z.string().optional(),
  brief: z.string().optional(),
  why_it_matters: z.string().optional(),
});

const sectionSchema = z.object({
  id: z.string(),
  title: z.string(),
  items: z.array(newsItemSchema),
});

const editions = defineCollection({
  loader: glob({ base: './src/content/editions', pattern: '**/*.{md,mdx}' }),
  schema: z.object({
    title: z.string(),
    date: z.string(),
    readTime: z.number(),
    editionKey: z.string(),
    sections: z.array(sectionSchema),
  }),
});

export const collections = { editions };
