/**
 * KOSIGN DRM × Notion — Apps Script proxy
 * ----------------------------------------------------------------------------
 * Why this exists:
 *   The Notion API has no Access-Control-Allow-Origin header, so a browser
 *   fetch() to https://api.notion.com/* is blocked by CORS. Apps Script Web
 *   Apps are server-side (Google's servers, not the user's browser), so we
 *   can call Notion freely and serve a flat JSON shape back to the frontend
 *   with permissive CORS.
 *
 * What it does:
 *   • Receives a GET request with ?empId=EMP-048
 *   • Queries the Notion database for the matching row (by the "EMP ID" prop)
 *   • Flattens Notion's nested property format into the exact shape that
 *     mock_notion_employees.json uses, so the same fetchEmployeeNotion() in
 *     index.html consumes both interchangeably
 *   • Returns { employee: {...} } as JSON
 *
 * Setup (≈ 5 minutes):
 *   1. Create a new Notion integration:
 *        https://www.notion.so/my-integrations → "New integration"
 *      Copy the "Internal Integration Token" (starts with secret_…).
 *   2. Open your Notion Employee database page → "..." menu → Connections →
 *      add the integration so it can read the database.
 *   3. Copy the database ID from the URL: notion.so/<workspace>/<DB_ID>?...
 *      (32-char hex string).
 *   4. https://script.google.com → New project → paste THIS FILE.
 *   5. ⚙ Project Settings → Script properties → add two properties:
 *        NOTION_TOKEN        = secret_xxx...        (from step 1)
 *        NOTION_DATABASE_ID  = 32-char-hex          (from step 3)
 *   6. Deploy → New deployment → type "Web app".
 *        Execute as: Me
 *        Who has access: Anyone
 *      Copy the /exec URL it gives you.
 *   7. In index.html, set:
 *        const NOTION_PROXY_URL = '<your /exec URL>';
 *      The drawer immediately switches from mock JSON to live Notion data.
 *
 * Schema mapping (edit PROP_NAMES below to match YOUR Notion column titles):
 *   - "EMP ID"        → id          (rich_text or title)
 *   - "Name"          → name        (title or rich_text)
 *   - "Nickname"      → nick        (rich_text)
 *   - "Gender"        → gender      (select)
 *   - "University"    → university  (rich_text)
 *   - "Email"         → email       (email)
 *   - "Languages"     → languages   (multi_select)
 *   - "Certificates"  → certificates (multi_select)
 *   - "Tech Experience" → techExperience (rich_text — bullets split on \n)
 *   - "Photo"         → photoUrl    (files & media — first file's URL)
 *   - "Resume"        → files       (files & media — array of {name,url})
 */

// EDIT THESE to match your Notion column titles exactly.
const PROP_NAMES = {
  empId:          'EMP ID',
  name:           'Name',
  nick:           'Nickname',
  gender:         'Gender',
  university:     'University',
  email:          'Email',
  languages:      'Languages',
  certificates:   'Certificates',
  techExperience: 'Tech Experience',
  photo:          'Photo',
  files:          'Resume'
};

function doGet(e) {
  const empId = (e.parameter && e.parameter.empId) || '';
  if (!empId) return jsonResponse({ employee: null, error: 'empId required' });

  const TOKEN = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  const DB_ID = PropertiesService.getScriptProperties().getProperty('NOTION_DATABASE_ID');
  if (!TOKEN || !DB_ID) {
    return jsonResponse({ employee: null, error: 'NOTION_TOKEN / NOTION_DATABASE_ID not set in Script Properties' });
  }

  try {
    const res = UrlFetchApp.fetch(
      `https://api.notion.com/v1/databases/${DB_ID}/query`,
      {
        method: 'post',
        contentType: 'application/json',
        muteHttpExceptions: true,
        headers: {
          Authorization: `Bearer ${TOKEN}`,
          'Notion-Version': '2022-06-28'
        },
        payload: JSON.stringify({
          filter: {
            property: PROP_NAMES.empId,
            rich_text: { equals: empId }
          },
          page_size: 1
        })
      }
    );
    if (res.getResponseCode() !== 200) {
      return jsonResponse({ employee: null, error: 'notion HTTP ' + res.getResponseCode(), detail: res.getContentText().slice(0, 300) });
    }
    const body = JSON.parse(res.getContentText());
    const page = (body.results || [])[0];
    if (!page) return jsonResponse({ employee: null });
    return jsonResponse({ employee: flattenPage(page) });
  } catch (err) {
    return jsonResponse({ employee: null, error: String(err) });
  }
}

// Walk the page properties and pull values out in the shape the frontend expects.
function flattenPage(page) {
  const props = page.properties || {};
  const text = (p) => {
    if (!p) return '';
    if (p.title)      return (p.title[0]?.plain_text)      || '';
    if (p.rich_text)  return (p.rich_text.map(x => x.plain_text).join('')) || '';
    if (p.email)      return p.email || '';
    if (p.select)     return p.select?.name || '';
    return '';
  };
  const multi = (p) => (p?.multi_select || []).map(x => x.name);
  const firstFileUrl = (p) => {
    const f = (p?.files || [])[0];
    return f ? (f.external?.url || f.file?.url || '') : null;
  };
  const allFiles = (p) => (p?.files || []).map(f => ({
    name: f.name || '(파일)',
    url:  f.external?.url || f.file?.url || '#',
    type: (f.name || '').split('.').pop().toLowerCase()
  }));
  // Tech experience is stored as a multi-line rich_text; split on newlines into bullets.
  const bullets = (p) => {
    const raw = text(p);
    if (!raw) return [];
    return raw.split('\n').map(s => s.trim()).filter(Boolean);
  };

  return {
    id:             text(props[PROP_NAMES.empId]),
    name:           text(props[PROP_NAMES.name]),
    nick:           text(props[PROP_NAMES.nick]),
    gender:         text(props[PROP_NAMES.gender]),
    university:     text(props[PROP_NAMES.university]),
    email:          text(props[PROP_NAMES.email]),
    languages:      multi(props[PROP_NAMES.languages]),
    certificates:   multi(props[PROP_NAMES.certificates]),
    techExperience: bullets(props[PROP_NAMES.techExperience]),
    photoUrl:       firstFileUrl(props[PROP_NAMES.photo]),
    files:          allFiles(props[PROP_NAMES.files])
  };
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
