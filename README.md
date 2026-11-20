# Replication of “Show Me!” The Informativeness of Images in Firms’ Annual Reports

This project replicates selected analyses from Ben-Rephael, Ronen, Ronen, and Zhou (2026). It uses SigLIP and DINOv3 to classify visual content in corporate annual reports and constructs firm-year measures of how often each type of visual appears. Stata is used for descriptive statistics and regression analysis. [Original paper](https://doi.org/10.1007/s11142-026-09975-y)

## Differences from the original study

1. **Visual classification and computing costs.** The original study uses TensorFlow to classify full annual report pages and uses Google Vision labels and rules to help identify visual categories. Our Python workflow uses PaddleOCR to detect and crop visual regions, then fine-tunes pretrained SigLIP and DINOv3 models separately on labeled crops. For each model, we update only the last two encoder layers and the classification head. This limits the number of parameters updated during training and avoids Google Vision API calls in the classification workflow.

2. **Page assignment by visual area.** The original study classifies each visual page using the full page as input. Our workflow classifies individual crops, sums their areas by predicted category within each page, and assigns the page to the category with the largest total area. For example, two photos covering 30 square units each outweigh a chart covering 50 square units, so the page counts as a photo page.

3. **Visual categories.** The five visual page categories in the original study are photos, team photos, charts, maps, and infographics. Our workflow also tracks logos and tables. Crops classified as `Other` are excluded from page assignment and firm-year counts.

## Outputs and statistical analysis

The Python scripts produce crop-level predictions, page classifications, and firm-year page counts. The Stata script uses prepared firm-year and analyst forecast datasets to generate replication outputs for Tables 1 through 7, including descriptive statistics and regressions on image page counts and analyst forecast errors. For comparison with the original study, the Stata script combines chart, map, and infographic page counts into `CMIC`.
