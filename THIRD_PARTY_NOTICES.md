# Third-party notices

## FreshRetailNet-50K data

`backend/data/freshretail_sample.csv` contains a selected subset of the [FreshRetailNet-50K dataset](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K), developed by Dingdong-Inc and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The source revision, selection criteria, date range, and file hash are described in `backend/data/source.json` and the project README. The dataset was filtered to the selected store-product pairs and relevant columns and converted to CSV.

Suggested citation: Wang et al., “FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail”, 2025, [arXiv:2505.16319](https://arxiv.org/abs/2505.16319).

## Netlify Identity browser bundle

`frontend/vendor/identity-client.js` bundles `@netlify/identity` 2.0.1 (author: Netlify Inc.; package metadata identifies the license as MIT; source: https://github.com/netlify/primitives/tree/main/packages/identity/prod) and `gotrue-js` 1.0.1 (https://github.com/netlify/gotrue-js), also MIT licensed. The installed `@netlify/identity` package does not include a separate copyright or license file; its package metadata is the source of the above attribution and license identifier. The `gotrue-js` distribution includes the following notice:

```text
MIT License

Copyright (c) 2020 Netlify

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Other dependencies installed by package managers have their own license terms.
