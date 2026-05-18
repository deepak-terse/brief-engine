CATEGORIES = {
  "LOCAL": "Local",
  "CIVIC": "Civic",
  "POLITICS": "Politics",
  "SPORTS": "Sports",
  "SOCIETY": "Society",
  "LIFESTYLE": "Lifestyle",
  "ENTERTAINMENT": "Entertainment",
  "BUSINESS": "Business",
  "TOP": "Top"
}

SCOPES = {
  "POWAI": "Powai",
  "MUMBAI": "Mumbai",
  "INDIA": "India",
  "WORLD": "World"
}

ARTICLE_SOURCES = [
  {"id": 1, "name": "Mumbai Live", "url": "https://www.mumbailive.com/"},
  {"id": 2, "name": "Google News", "url": "https://news.google.com/"},
  {"id": 3, "name": "The Hindu", "url": "https://www.thehindu.com/"}
]

RSS_FEEDS = [
  # Mumbai Live feeds - Mumbai scope
  {"id": 1, "articleSourceId": 1, "category": CATEGORIES["TOP"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/latest.xml"},
  {"id": 2, "articleSourceId": 1, "category": CATEGORIES["SPORTS"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/sports.xml"},
  {"id": 3, "articleSourceId": 1, "category": CATEGORIES["POLITICS"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/politics.xml"},
  {"id": 4, "articleSourceId": 1, "category": CATEGORIES["ENTERTAINMENT"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/entertainment.xml"},
  {"id": 5, "articleSourceId": 1, "category": CATEGORIES["CIVIC"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/civic.xml"},
  {"id": 6, "articleSourceId": 1, "category": CATEGORIES["LIFESTYLE"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/lifestyle.xml"},
  {"id": 7, "articleSourceId": 1, "category": CATEGORIES["SOCIETY"], "scope": SCOPES["MUMBAI"], "url": "https://www.mumbailive.com/rss/en/society.xml"},
  
  # Google News feed - Mumbai scope
  {"id": 8, "articleSourceId": 2, "category": CATEGORIES["TOP"], "scope": SCOPES["MUMBAI"], "url": "https://news.google.com/rss/search?q=Powai+Mumbai+when:2d"},
  
  # The Hindu feeds - India and World scopes
  {"id": 10, "articleSourceId": 3, "category": CATEGORIES["TOP"], "scope": SCOPES["INDIA"], "polling_interval": 240, "url": "https://www.thehindu.com/news/national/feeder/default.rss"},
  {"id": 11, "articleSourceId": 3, "category": CATEGORIES["TOP"], "scope": SCOPES["WORLD"], "url": "https://www.thehindu.com/news/international/feeder/default.rss"}
]

DEFAULT_POLLING_INTERVAL = 1440  # in minutes (24 hours)
FRESHNESS_DAYS = 2
SPACY_MODEL = "en_core_web_sm"
SENTENCE_MODEL = "all-MiniLM-L6-v2"
TARGET_LABELS = {"PERSON", "ORG", "GPE", "LOC", "EVENT", "PRODUCT"}
CLUSTER_DISTANCE_THRESHOLD = 0.55

BRIEF_TEMPLATES = [
  # ──────────────────────────────────────────────────────────────────
  # Template 1: Original morning edition (kept for backward compat)
  # ──────────────────────────────────────────────────────────────────
  {
    "name": "powai_morning_edition",
    "title": "Today in Powai & Mumbai",
    "max_read_time_minutes": 5,
    "selection": {
      "max_total_items": 15,
      "dedupe_categories_per_section": 2,
      "min_importance_score": 0.35,
      "min_recency_score": 0.25
    },
    "scope_priority": {
      "Powai": 1.0,
      "Mumbai": 0.85,
      "India": 0.55,
      "World": 0.35
    },
    "sections": [
      {
        "id": "right_now",
        "title": "⚡ Right Now",
        "description": "Immediate updates affecting today",
        "format": "one_line",
        "limit": 5,
        "required": True,
        "sort": {
          "importance": 0.6,
          "recency": 0.4
        },
        "filters": {
          "scope": ["Powai", "Mumbai"],
          "category": [
            "Safety",
            "Transport",
            "Weather"
          ],
          "min_importance_score": 0.4
        }
      },
      {
        "id": "powai_pulse",
        "title": "📍 Powai Pulse",
        "description": "What's changing around Powai",
        "format": "short",
        "limit": 4,
        "required": True,
        "sort": {
          "importance": 0.5,
          "recency": 0.3,
          "scope": 0.2
        },
        "filters": {
          "scope": ["Powai"],
          "category": [
            "Infra",
            "Transport",
            "Safety",
            "Community",
            "Environment",
            "Healthcare",
            "Education"
          ]
        }
      },
      {
        "id": "mumbai_moves",
        "title": "🚆 Mumbai Moves",
        "description": "City-level changes affecting daily life",
        "format": "short",
        "limit": 4,
        "required": True,
        "sort": {
          "importance": 0.5,
          "recency": 0.3,
          "scope": 0.2
        },
        "filters": {
          "scope": ["Mumbai"],
          "category": [
            "Transport",
            "Infra",
            "Politics",
            "Healthcare",
            "Environment",
            "Safety"
          ]
        }
      },
      {
        "id": "money_rules",
        "title": "💰 Money & Rules",
        "description": "Policies, prices and financial impact",
        "format": "explainer",
        "limit": 3,
        "required": True,
        "sort": {
          "importance": 0.7,
          "recency": 0.3
        },
        "filters": {
          "scope": [
            "Mumbai",
            "India",
            "World"
          ],
          "category": [
            "Business",
            "Politics"
          ],
          "min_importance_score": 0.5
        }
      },
      {
        "id": "beyond_city",
        "title": "🌍 Beyond Mumbai",
        "description": "National and global stories worth your attention",
        "format": "short",
        "limit": 2,
        "required": False,
        "sort": {
          "importance": 0.7,
          "recency": 0.3
        },
        "filters": {
          "scope": [
            "India",
            "World"
          ],
          "category": [
            "Politics",
            "Business",
            "Environment",
            "Healthcare"
          ]
        }
      },
      {
        "id": "worth_attention",
        "title": "👀 Worth Your Attention",
        "description": "Interesting but not urgent",
        "format": "one_line",
        "limit": 3,
        "required": False,
        "sort": {
          "importance": 0.5,
          "recency": 0.5
        },
        "filters": {
          "scope": [
            "Powai",
            "Mumbai"
          ],
          "category": [
            "Lifestyle",
            "Sports",
            "Community",
            "Education"
          ]
        }
      }
    ]
  },
  {
  "name": "powai_pulse",
  "title": "Powai Pulse",
  "subtitle": "Hyperlocal news for Powai residents — traffic, civic updates, safety, policy, and city impact in under 5 minutes.",
  "max_read_time_minutes": 5,

  "branding": {
    "style": "minimal_dark_newsroom",
    "voice": "calm_useful_direct",
    "layout_density": "compact",
    "emoji_section_headers": True,
    "show_tags": True,
    "show_why_it_matters": True,
    "show_subscription_cta_midway": True
  },

  "selection": {
    "max_total_items": 18,
    "dedupe_categories_per_section": 2,
    "min_importance_score": 0.35,
    "min_recency_score": 0.25,
    "summary_max_words": 34,
    "headline_style": "conversational_direct",

    "story_mix": {
      "full_explainers": 6,
      "compact_briefs": 10,
      "alerts": 2
    }
  },

  "scope_priority": {
    "Powai": 1.0,
    "Mumbai": 0.82,
    "Maharashtra": 0.58,
    "India": 0.42,
    "World": 0.22
  },

  "editorial_rules": {
    "primary_goal": "Deliver a highly scannable hyperlocal intelligence briefing for Powai residents with immediate personal relevance.",

    "avoid_generic_news": True,

    "avoid_topics_without_local_relevance": [
      "celebrity gossip",
      "viral internet drama",
      "abstract geopolitics without India impact",
      "long political speeches",
      "generic sports coverage",
      "crime without civic or safety relevance"
    ],

    "prefer_story_types": [
      "traffic",
      "water cuts",
      "safety incidents",
      "transport disruptions",
      "civic infrastructure",
      "local crime alerts",
      "education policy",
      "fuel prices",
      "metro and railway updates",
      "municipal policy",
      "inflation",
      "housing",
      "weather",
      "government regulation",
      "India-impact global news"
    ],

    "newsletter_style_rules": {
      "headline_max_words": 14,
      "summary_max_words": 38,
      "prefer_conversational_headlines": True,
      "avoid_newspaper_tone": True,
      "avoid_clickbait": True,
      "avoid_passive_voice": True,
      "prioritize_clarity_over_drama": True,
      "prefer_short_paragraphs": True,
      "prefer_mobile_readability": True
    },

    "reader_impact_rules": {
      "every_lead_story_requires_impact_line": True,
      "impact_line_prefix": "Why it matters",
      "impact_line_style": "practical_reader_consequence"
    },

    "layout_rules": {
      "section_header_style": "emoji_plus_title",
      "show_section_descriptions": True,
      "mix_long_and_short_cards": True,
      "max_consecutive_long_cards": 2,
      "insert_subscription_cta_after_second_section": True,
      "prefer_bullets_over_paragraphs": True,
      "prioritize_scannability": True,
      "prefer_short_cards": True,
      "compact_tag_display": True
    },

    "story_selection_rules": {
      "prefer_unique_topics": True,
      "avoid_repeating_same_category": True,
      "require_at_least_one_powai_story": True,
      "require_at_least_one_high_utility_story": True,
      "require_at_least_one_reader_cost_story": True,
      "prefer_local_over_national": True,
      "global_news_requires_india_angle": True
    },

    "tone_rules": {
      "feel_like_local_intelligence_briefing": True,
      "feel_personal_and_relevant": True,
      "avoid_feeling_like_news_website": True,
      "calm_and_useful": True,
      "direct_but_not_alarmist": True
    }
  },

  "sections": [
    {
      "id": "heads_up",
      "title": "🚨 Heads Up",
      "description": "Immediate impact — traffic, outages, safety",
      "scope_label": "ALERTS",
      "format": "lead_alert_plus_briefs",

      "lead_count": 1,
      "brief_count": 1,

      "limit": 2,
      "required": True,

      "sort": {
        "importance": 0.6,
        "recency": 0.4
      },

      "filters": {
        "scope": [
          "Powai",
          "Mumbai"
        ],

        "category": [
          "Transport",
          "Safety",
          "Weather",
          "Infra"
        ],

        "min_importance_score": 0.4
      },

      "card_rules": {
        "lead_story_requires_full_summary": True,
        "brief_story_format": "headline_plus_tags_only",
        "show_tags": True,
        "allow_incident_alerts": True
      }
    },

    {
      "id": "ground_zero",
      "title": "📍 Ground Zero",
      "description": "Powai hyperlocal news",
      "scope_label": "POWAI",
      "format": "lead_plus_briefs",

      "lead_count": 1,
      "brief_count": 2,

      "limit": 3,
      "required": True,

      "sort": {
        "importance": 0.5,
        "recency": 0.3,
        "scope": 0.2
      },

      "filters": {
        "scope": [
          "Powai"
        ],

        "category": [
            "Infra",
            "Transport",
            "Safety",
            "Community",
            "Environment",
            "Healthcare",
            "Education",
						"Lifestyle"
          ],
      },

      "card_rules": {
        "lead_story_requires_why_it_matters": True,
        "brief_story_format": "headline_plus_tags_only",
        "show_tags": True
      }
    },

    {
      "id": "mumbai_matters",
      "title": "🏙️ Mumbai Matters",
      "description": "City-wide civic, transport, Infra",
      "scope_label": "MUMBAI",
      "format": "lead_plus_briefs",

      "lead_count": 1,
      "brief_count": 3,

      "limit": 4,
      "required": True,

      "sort": {
        "importance": 0.5,
        "recency": 0.3,
        "scope": 0.2
      },

      "filters": {
        "scope": [
          "Mumbai"
        ],

         "category": [
            "Transport",
            "Infra",
            "Politics",
            "Healthcare",
            "Environment",
            "Safety"
          ]
      },

      "card_rules": {
        "lead_story_requires_full_summary": True,
        "lead_story_requires_why_it_matters": True,
        "brief_story_format": "headline_plus_tags_only"
      }
    },

    {
      "id": "wallet_watch",
      "title": "💸 Wallet Watch",
      "description": "Fuel, inflation, EMIs, real estate, jobs",
      "scope_label": "MONEY",
      "format": "lead_plus_briefs",

      "lead_count": 1,
      "brief_count": 2,

      "limit": 3,
      "required": True,

      "sort": {
        "importance": 0.72,
        "recency": 0.28
      },

      "filters": {
        "scope": [
          "Mumbai",
          "India",
          "World"
        ],

        "category": [
          "Business"
        ],

        "min_importance_score": 0.5
      },

      "card_rules": {
        "focus_on_consumer_impact": True,
        "every_lead_requires_cost_implication": True
      }
    },

    {
      "id": "policy_radar",
      "title": "🏛️ Policy Radar",
      "description": "Government decisions, regulations, civic policy",
      "scope_label": "POLICY",
      "format": "lead_plus_briefs",

      "lead_count": 1,
      "brief_count": 2,

      "limit": 3,
      "required": True,

      "sort": {
        "importance": 0.7,
        "recency": 0.3
      },

      "filters": {
        "scope": [
          "Maharashtra",
          "India"
        ],

        "category": [
          "Politics"
        ],

        "min_importance_score": 0.5
			},	
      "card_rules": {
        "lead_story_requires_why_it_matters": True,
        "policy_stories_must_have_reader_relevance": True
      }
    },

    {
      "id": "nation_scan",
      "title": "🇮🇳 Nation Scan",
      "description": "National news filtered for real impact",
      "scope_label": "INDIA",
      "format": "compact_briefs",

      "limit": 2,
      "required": True,

      "sort": {
        "importance": 0.7,
        "recency": 0.3
      },

      "filters": {
        "scope": [
          "India"
        ],

        "category": [
            "Politics",
            "Business",
            "Environment",
            "Healthcare",
						"Sports"
          ]
      },

      "card_rules": {
        "format": "headline_plus_tags_only",
        "must_feel_relevant_to_indian_reader": True
      }
    },

    {
      "id": "world_wire",
      "title": "🌐 World Wire",
      "description": "Global news translated to India impact",
      "scope_label": "GLOBAL",
      "format": "lead_plus_briefs",

      "lead_count": 2,
      "brief_count": 0,

      "limit": 2,
      "required": True,

      "sort": {
        "importance": 0.90,
        "recency": 0.10
      },

      "filters": {
        "scope": [
          "World"
        ],

        "category": [
            "Politics",
            "Business",
            "Environment",
            "Healthcare"
          ],
      },

      "card_rules": {
        "every_story_requires_india_impact": True,
        "require_why_it_matters": True,
        "avoid_generic_world_news": True
      }
    }
  ]
}
]