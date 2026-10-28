"""GraphQL documents used by the collector (kept separate so they can be
validated against GitHub's public schema in tests)."""

DISCOVER = """
query Discover($q: String!, $after: String) {
  rateLimit { cost remaining resetAt }
  search(type: REPOSITORY, query: $q, first: 100, after: $after) {
    repositoryCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Repository {
        nameWithOwner
        stargazerCount
        isArchived
        isFork
        licenseInfo { spdxId }
        repositoryTopics(first: 30) { nodes { topic { name } } }
      }
    }
  }
}
"""

# The repository query is assembled from top-level selections keyed by their
# response name (the alias when there is one).  Any of them except "meta" can be
# dropped at run time: GraphQL nulls the *whole* repository when a non-null field
# errors, and fine-grained personal access tokens are refused some fields
# (stargazers with starredAt, for one), so a single forbidden field would
# otherwise cost us every repository.  See collect.fetch_core.
REPO_CORE_FIELDS = [
    ("meta", """nameWithOwner
    name
    description
    url
    homepageUrl
    createdAt
    pushedAt
    isArchived
    isFork
    isDisabled
    stargazerCount
    forkCount
    hasIssuesEnabled
    licenseInfo { spdxId name key }
    primaryLanguage { name }
    repositoryTopics(first: 30) { nodes { topic { name } } }
    owner { __typename login }"""),
    ("watchers", "watchers { totalCount }"),
    ("codeOfConduct", "codeOfConduct { key name }"),
    ("contributingGuidelines", "contributingGuidelines { url }"),
    ("isSecurityPolicyEnabled", "isSecurityPolicyEnabled"),
    ("issueTemplates", "issueTemplates { name }"),
    ("pullRequestTemplates", "pullRequestTemplates { filename }"),
    ("openIssues", "openIssues: issues(states: OPEN) { totalCount }"),
    ("openPRs", "openPRs: pullRequests(states: OPEN) { totalCount }"),
    ("defaultBranchRef", """defaultBranchRef {
      name
      target {
        ... on Commit {
          committedDate
          recent90: history(since: $since90) { totalCount }
          history(since: $since180, first: 100) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { committedDate author { user { login } email name } }
          }
        }
      }
    }"""),
    ("releases", """releases(first: 30, orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      nodes { tagName name createdAt publishedAt isPrerelease isDraft }
    }"""),
    ("tags", """tags: refs(refPrefix: "refs/tags/", first: 30, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      totalCount
      nodes {
        name
        target {
          ... on Tag { tagger { date } }
          ... on Commit { committedDate }
        }
      }
    }"""),
    ("recentIssues", """recentIssues: issues(first: 40, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        createdAt closedAt
        author { login }
        comments(first: 3) { nodes { createdAt author { login } } }
      }
    }"""),
    ("recentPRs", """recentPRs: pullRequests(first: 40, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        createdAt mergedAt closedAt
        author { login }
        reviews(first: 1) { nodes { createdAt author { login } } }
        comments(first: 2) { nodes { createdAt author { login } } }
      }
    }"""),
    ("stargazers", "stargazers(first: 100, orderBy: {field: STARRED_AT, direction: DESC}) { edges { starredAt } }"),
    ("forks", "forks(first: 100, orderBy: {field: CREATED_AT, direction: DESC}) { nodes { createdAt } }"),
    ("root", 'root: object(expression: "HEAD:") { ... on Tree { entries { name type } } }'),
    ("dotgithub", 'dotgithub: object(expression: "HEAD:.github") { ... on Tree { entries { name type } } }'),
    ("workflows", 'workflows: object(expression: "HEAD:.github/workflows") { ... on Tree { entries { name type } } }'),
    ("docsDir", 'docsDir: object(expression: "HEAD:docs") { ... on Tree { entries { name type } } }'),
    ("readmeMd", 'readmeMd: object(expression: "HEAD:README.md") { ... on Blob { text byteSize } }'),
    ("readmeRst", 'readmeRst: object(expression: "HEAD:README.rst") { ... on Blob { text } }'),
    ("readmeLower", 'readmeLower: object(expression: "HEAD:readme.md") { ... on Blob { text } }'),
    ("readmePlain", 'readmePlain: object(expression: "HEAD:README") { ... on Blob { text } }'),
]

REMOVABLE_CORE_FIELDS = frozenset(key for key, _ in REPO_CORE_FIELDS if key != "meta")


def build_repo_core(exclude=()):
    """The RepoCore document without the given top-level selections."""
    exclude = set(exclude) - {"meta"}
    body = "\n    ".join(text for key, text in REPO_CORE_FIELDS if key not in exclude)
    return (
        "query RepoCore($owner: String!, $name: String!, $since180: GitTimestamp!, $since90: GitTimestamp!) {\n"
        "  rateLimit { cost remaining resetAt }\n"
        "  repository(owner: $owner, name: $name) {\n"
        "    " + body + "\n"
        "  }\n"
        "}\n"
    )


REPO_CORE = build_repo_core()

# Fields that some token types are not allowed to read.  GitHub Sponsors data
# (hasSponsorsListing) is off-limits to fine-grained personal access tokens,
# and in GraphQL an error on a non-null field nulls out its parents all the
# way up to `repository`.  Keeping these in their own small queries means a
# FORBIDDEN answer costs us the optional field, not the whole repository.
REPO_EXTRAS = """
query RepoExtras($owner: String!, $name: String!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    fundingLinks { platform url }
    mentionableUsers { totalCount }
  }
}
"""

REPO_SPONSORS = """
query RepoSponsors($owner: String!, $name: String!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    owner {
      ... on Organization { hasSponsorsListing }
      ... on User { hasSponsorsListing }
    }
  }
}
"""

MORE_HISTORY = """
query MoreHistory($owner: String!, $name: String!, $since180: GitTimestamp!, $after: String!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(since: $since180, first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate author { user { login } email name } }
          }
        }
      }
    }
  }
}
"""

# Time-windowed counts via the search API (each alias is one search).
COUNTS = """
query RepoCounts(
  $issuesOpened: String!, $issuesClosed: String!,
  $prsOpened: String!, $prsMerged: String!, $prsClosed: String!,
  $staleIssues: String!, $breaking: String!
) {
  rateLimit { cost remaining resetAt }
  issuesOpened: search(type: ISSUE, query: $issuesOpened) { issueCount }
  issuesClosed: search(type: ISSUE, query: $issuesClosed) { issueCount }
  prsOpened: search(type: ISSUE, query: $prsOpened) { issueCount }
  prsMerged: search(type: ISSUE, query: $prsMerged) { issueCount }
  prsClosed: search(type: ISSUE, query: $prsClosed) { issueCount }
  staleIssues: search(type: ISSUE, query: $staleIssues) { issueCount }
  breaking: search(type: ISSUE, query: $breaking) { issueCount }
}
"""
