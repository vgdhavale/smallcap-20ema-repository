# Smallcap Stocks Near 20 EMA

This repository identifies Smallcap stocks from the latest month of a Chartink
backtest that are trading within 2% of their 20-day EMA.

The resulting stock names are published on the repository GitHub Pages webpage
and saved as:

```text
smallcap_stocks_near_20ema.csv
```

## Run manually

1. Open the **Actions** tab.
2. Select **Update Smallcap 20 EMA List**.
3. Click **Run workflow**.
4. Provide the public Google Drive folder URL and Chartink CSV filename.
5. Click **Run workflow**.

The workflow downloads the Chartink CSV, calculates the 20 EMA using Yahoo
Finance NSE price data, creates the result CSV, commits it to the repository,
and uploads it as a workflow artifact.

## Webpage

After GitHub Pages is enabled, open:

```text
https://YOUR_USERNAME.github.io/YOUR_REPO_NAME/
```

The page displays the stock names from the latest CSV and includes a CSV
download button.

## Enable GitHub Pages

1. Go to **Settings**.
2. Open **Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select the `main` branch.
5. Select `/ (root)` as the folder.
6. Click **Save**.
