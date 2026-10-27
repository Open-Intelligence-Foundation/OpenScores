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

REPO_CORE = """
query RepoCore($owner: String!, $name: String!, $since180: GitTimestamp!, $since90: GitTimestamp!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    nameWithOwner
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
    watchers { totalCount }
    licenseInfo { spdxId name key }
    primaryLanguage { name }
    repositoryTopics(first: 30) { nodes { topic { name } } }
    owner {
      __typename
      login
      ... on Organization { hasSponsorsListing }
      ... on User { hasSponsorsListing }
    }
    fundingLinks { platform url }
    codeOfConduct { key name }
    contributingGuidelines { url }
    isSecurityPolicyEnabled
    issueTemplates { name }
    pullRequestTemplates { filename }
    hasIssuesEnabled
    mentionableUsers { totalCount }
    openIssues: issues(states: OPEN) { totalCount }
    openPRs: pullRequests(states: OPEN) { totalCount }
    defaultBranchRef {
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
    }
    releases(first: 30, orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      nodes { tagName name createdAt publishedAt isPrerelease isDraft }
    }
    tags: refs(refPrefix: "refs/tags/", first: 30, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      totalCount
      nodes {
        name
        target {
          ... on Tag { tagger { date } }
          ... on Commit { committedDate }
        }
      }
    }
    recentIssues: issues(first: 40, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        createdAt closedAt
        author { login }
        comments(first: 3) { nodes { createdAt author { login } } }
      }
    }
    recentPRs: pullRequests(first: 40, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        createdAt mergedAt closedAt
        author { login }
        reviews(first: 1) { nodes { createdAt author { login } } }
        comments(first: 2) { nodes { createdAt author { login } } }
      }
    }
    stargazers(first: 100, orderBy: {field: STARRED_AT, direction: DESC}) { edges { starredAt } }
    forks(first: 100, orderBy: {field: CREATED_AT, direction: DESC}) { nodes { createdAt } }
    root: object(expression: "HEAD:") { ... on Tree { entries { name type } } }
    dotgithub: object(expression: "HEAD:.github") { ... on Tree { entries { name type } } }
    workflows: object(expression: "HEAD:.github/workflows") { ... on Tree { entries { name type } } }
    docsDir: object(expression: "HEAD:docs") { ... on Tree { entries { name type } } }
    readmeMd: object(expression: "HEAD:README.md") { ... on Blob { text byteSize } }
    readmeRst: object(expression: "HEAD:README.rst") { ... on Blob { text } }
    readmeLower: object(expression: "HEAD:readme.md") { ... on Blob { text } }
    readmePlain: object(expression: "HEAD:README") { ... on Blob { text } }
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
