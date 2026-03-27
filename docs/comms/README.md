# FFmemes Content Strategy

Content workspace for @ffmemes Telegram channel (https://t.me/ffmemes).

**Target cadence**: ~1 post per day
**Language**: Russian only
**Tone**: dania-zip rules (https://github.com/ohld/dania-zip)
**Approval**: All posts require CEO approval before publishing

## Structure

```
docs/comms/
  content-plan.md    # Post categories, ideas, suggested schedule
  brand-guide.md     # Visual identity: colors, font, chart palette
  lore/              # Historical archive (channel history, vc.ru article, milestones)
  drafts/            # Comms agent drafts awaiting CEO approval
  published/         # Published post archive for reference
```

## Workflow

1. Comms agent reads content plan + Analyst reports
2. Picks next post from schedule or creates data-driven post
3. Drafts post as Paperclip issue with text + visual description
4. CEO reviews and approves
5. Agent posts to @ffmemes channel
6. Post moved to `published/` with date prefix

## Links

- Content plan: [content-plan.md](content-plan.md)
- Brand guide: [brand-guide.md](brand-guide.md)
- Lore archive: [lore/](lore/)
- Tone of voice: https://github.com/ohld/dania-zip
- Comms agent spec: [../../agents/comms/AGENTS.md](../../agents/comms/AGENTS.md)
