# Meta / Instagram Graph API Setup

End-to-end walkthrough for getting `IG_USER_ID` and `IG_ACCESS_TOKEN` for the AIRA Social Media Agent.

**Path chosen:** existing personal FB profile + new FB Page + new dummy IG + new Meta App.

> Your personal FB profile is just the Meta App owner and Page admin — it never publishes. The dummy IG account is the only public surface. This is the standard agency pattern.

**Time:** 30–60 min of clicking. No review wait.

**End state:** `.env` has `IG_USER_ID` and `IG_ACCESS_TOKEN` (a long-lived Page token) populated.

---

## Step 1 — Log in to your personal Facebook

Use your existing personal FB profile. We're skipping the brand-new-FB-account path because it triggers Meta's day-one review process (can take 24h+, sometimes asks for ID upload).

You will:
- Create a new **FB Page** under your personal profile (Step 2)
- Create a new **IG account** (Step 3)
- Create a new **Meta App** (Step 6)

Your personal profile is the *admin/owner* of all three. It does not publish anything itself.

---

## Step 2 — Create the Facebook Page

A Page is a separate object from your profile. The bot will publish *as* this Page's linked Instagram account.

1. Still logged in as your personal FB profile, go to https://www.facebook.com/pages/create
2. Page name: `AIRA Social Test` (or whatever — won't be publicly visible to your audience)
3. Category: `App Page` or `Software`
4. Skip the optional fields (bio, address, etc.) — you can come back to these
5. Click **Create Page**
6. **Note the Page ID:** Settings → About → scroll to bottom → "Page ID" is a numeric string. Save it somewhere — we'll need it.

---

## Step 3 — Create the dummy Instagram account

1. Open the **Instagram mobile app** (or https://www.instagram.com/accounts/emailsignup/)
2. Sign up with a fresh email (different from FB if possible — or another Gmail alias)
3. Username: something like `aira_social_test`
4. Skip "find friends" prompts
5. Verify the email

---

## Step 4 — Convert IG to a Business / Creator account

The Graph API requires this. Personal IG accounts cannot publish via the API.

1. In the IG mobile app: **Profile → ☰ menu → Settings and privacy → Account type and tools**
2. Tap **Switch to professional account**
3. Pick a category (`Education`, `Entrepreneur`, anything)
4. Choose **Business** (Creator also works, but Business is the standard)
5. When prompted, **link to your Facebook Page** from Step 2
   - Log in with the personal FB profile inside the IG app
   - Pick the `AIRA Social Test` Page
   - Confirm

**Verify the link:**
- Back on FB (on desktop), go to your Page → **Settings → Linked Accounts → Instagram**
- You should see the IG account listed

---

## Step 5 — Get your Instagram Business Account ID

1. Open https://developers.facebook.com/tools/explorer/
2. Log in with the personal FB profile (it'll ask you to create a developer account — say yes; that's Step 6)
3. (You may need to finish Step 6 first if the Graph API Explorer requires a Meta App selected — come back here right after)

---

## Step 6 — Create the Meta Developer App

1. Go to https://developers.facebook.com/
2. Click **Get Started** → accept the developer terms → verify phone
3. Click **My Apps → Create App**
4. **Use case:** `Other` (then click Next)
5. **App type:** `Business`
6. **App details:**
   - Display name: `AIRA Social Agent`
   - Contact email: same email as your dummy FB
   - Business portfolio: leave as default ("you'll create one for me")
7. Click **Create app** → it may ask for password confirmation

You're now in the App Dashboard.

---

## Step 7 — Add the Instagram Graph API product

1. In the left sidebar of the App Dashboard, find **Add product**
2. Look for **Instagram** → click **Set up**
   - If you see "Instagram Graph API" specifically, pick that. If only "Instagram" exists in newer Meta UI, that's fine — same thing under the hood.
3. Skip any quickstart wizards if they appear

---

## Step 8 — Add the IG account as a tester (bypasses App Review)

> 🎯 This is the key step that lets you use `instagram_content_publish` *without going through Meta's App Review process*. Apps in "Development mode" can publish to any IG account explicitly added as a tester.

1. In the App Dashboard sidebar: **App Roles → Roles** (or **Roles → Roles** in older UIs)
2. Under **Instagram Testers**, click **Add Instagram Testers**
3. Enter the dummy IG username (`aira_social_test`)
4. Click **Submit**
5. **Now, in the Instagram app:** Settings and privacy → Website permissions → Tester invites → Accept the invite

If you don't see "Instagram Testers" yet, also add yourself under **App Roles → People → Add People → Administrator**.

---

## Step 9 — Generate a short-lived User Access Token

1. Go to https://developers.facebook.com/tools/explorer/
2. Top right: **Meta App** dropdown → select **AIRA Social Agent**
3. **User or Page** dropdown → pick **User Token**
4. Click **Add a Permission** and add ALL of these (one at a time):
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
5. Click **Generate Access Token** → log in as the personal FB profile if prompted → grant all permissions
6. **Copy the token** that appears in the "Access Token" field. This is your **short-lived user token** — expires in ~1 hour. We exchange it for a long-lived one next.

Also click the **ⓘ** icon next to the token to verify it shows all the permissions you added.

---

## Step 10 — Exchange for a long-lived User Token (60 days)

Replace placeholders and run:

```powershell
$APP_ID = "<your app id from App Dashboard Settings > Basic>"
$APP_SECRET = "<your app secret from same page>"
$SHORT_TOKEN = "<the token you copied in Step 9>"

curl.exe "https://graph.facebook.com/v23.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$APP_ID&client_secret=$APP_SECRET&fb_exchange_token=$SHORT_TOKEN"
```

Response:
```json
{"access_token":"EAAxxx...","token_type":"bearer","expires_in":5183944}
```

The `expires_in` is seconds — 5,183,944 ≈ 60 days. Save this `access_token` — it's the **long-lived USER token**. We use this to fetch the Page token next.

---

## Step 11 — Get the long-lived Page Token

The Page token is what the bot actually uses. Page tokens derived from a long-lived user token **never expire** (as long as the user doesn't change password / revoke access).

```powershell
$LONG_USER_TOKEN = "<from Step 10>"

curl.exe "https://graph.facebook.com/v23.0/me/accounts?access_token=$LONG_USER_TOKEN"
```

Response (abbreviated):
```json
{
  "data": [
    {
      "access_token": "EAAyyy...",
      "id": "<page_id>",
      "name": "AIRA Social Test",
      ...
    }
  ]
}
```

Copy the `access_token` for the `AIRA Social Test` Page. **This is your `IG_ACCESS_TOKEN`.**

---

## Step 12 — Get the IG_USER_ID (Instagram Business Account ID)

```powershell
$PAGE_TOKEN = "<from Step 11>"
$PAGE_ID = "<your Page ID from Step 2>"

curl.exe "https://graph.facebook.com/v23.0/${PAGE_ID}?fields=instagram_business_account&access_token=$PAGE_TOKEN"
```

Response:
```json
{
  "instagram_business_account": { "id": "17841400000000000" },
  "id": "<page_id>"
}
```

That `instagram_business_account.id` is your **`IG_USER_ID`**.

---

## Step 13 — Verify end-to-end with a no-op call

Confirm the token actually works against the IG account:

```powershell
$IG_USER_ID = "<from Step 12>"
$IG_TOKEN = "<from Step 11>"

curl.exe "https://graph.facebook.com/v23.0/${IG_USER_ID}?fields=username,account_type&access_token=$IG_TOKEN"
```

Should return:
```json
{"username":"aira_social_test","account_type":"BUSINESS","id":"17841..."}
```

If you see `BUSINESS` (or `MEDIA_CREATOR`), you're good.

---

## Step 14 — Populate `.env`

```
IG_USER_ID=<from Step 12>
IG_ACCESS_TOKEN=<from Step 11>
IG_GRAPH_VERSION=v23.0
```

Done. Phase 6 code will pick these up when we wire the publisher.

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `OAuthException: (#100) Invalid parameter` on `me/accounts` | Used the short-lived token | Run Step 10 first |
| `instagram_business_account` is missing from the Page response | IG not linked to Page, or not converted to Business | Repeat Steps 4 + verify in FB Page Settings → Linked Accounts |
| `(#10) Application does not have permission` | App is in Dev Mode and target IG not added as tester | Repeat Step 8, ensure invite was accepted in IG app |
| Token expired suddenly | Long-lived user token hit 60 days; or password changed | Re-run Steps 9 → 11 to refresh |
| `Permissions error` for `instagram_content_publish` | Permission not granted during token gen | Re-run Step 9 and explicitly add this permission |
| FB asks for ID upload | New account flagged | Either upload ID, wait it out, or use your real FB profile |

---

## Reminders to set (do now, before you forget)

- **Calendar reminder ~55 days from today** (so 7 days before token expiry): "Refresh AIRA Social Media Agent Meta token"
- Keep `APP_ID` and `APP_SECRET` somewhere safe (NOT in git). Add to `.env` if you want me to wire automatic token refresh later — that's a v2 feature.
