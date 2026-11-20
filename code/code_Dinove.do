/*
Replicate Tables 1 through 7 for the annual report visual disclosure study.

Inputs
    table456_firm_year_merged_restored_visuals.csv
        Firm-year sample with page counts, firm identifiers, and controls.
    table7_analyst_firm_quarter_raw.csv
        Analyst-firm-quarter sample with forecast errors and regressors.

Outputs
    Table1-1.rtf through Table7-1.rtf.

Required Stata packages
    estout, winsor2, and reghdfe.
*/

cd "Replication/Dinove"
import delimited using "Replication/Dinove/Dinove_data.csv",clear
* Use the prepared base-sample indicator and retain fiscal years after 2001.
keep if base_sample_flag == 1
keep if fyear > 2001
* Keep one row per GVKEY and fiscal year for the report-level analysis.
duplicates drop gvkey fyear,force
xtset gvkey fyear
* Verify that every visual page count is a nonmissing, nonnegative integer.
foreach v in imgc tc chartc mapc infogc {
    assert !missing(`v')
    assert `v' >= 0 & `v' == floor(`v')
}
* Define CMIC as the sum of chart, map, and infographic pages.
gen cmic = chartc + mapc + infogc
gen visual_pages = imgc + tc + cmic
* Flag reports with at least one visual page for the visual subsample.
gen byte visual_sample = visual_pages > 0 if !missing(visual_pages)
tab visual_sample

* Table 1. Report length and visual page counts by sample
* Install estout if needed to summarize results and export the tables.
//capture which esttab
//if _rc ssc install estout
label variable reportpages "# Report Pages"
label variable imgc "IMGC"
label variable cmic "CMIC"
label variable chartc "CHARTC"
label variable mapc "MAPC"
label variable infogc "INFOGC"
label variable tc "TC"
* Compare the full and visual samples using complete cases within each sample.
estpost summarize reportpages imgc cmic chartc mapc infogc tc, detail listwise
eststo full
estpost summarize reportpages imgc cmic chartc mapc infogc tc if visual_sample == 1, detail listwise
eststo visual
* Export the mean, median, standard deviation, and firm-year count side by side.
esttab full visual using "Table1-1.rtf", replace ///
    cells("mean(fmt(3)) p50(fmt(3)) sd(fmt(3))") ///
    mtitles("Full Sample" "Visuals Sample") ///
    collabels("Mean" "Median" "Std. Dev.") ///
    stats(N, fmt(%12.0fc) labels("# of Firm-year Obs.")) ///
    label nonumbers nogaps ///
    varwidth(24) modelwidth(10) 
* Table 2. Report length and visual page counts by industry
preserve
keep if base_sample_flag == 1
tab gsector
* Return the mean and standard deviation for each variable on a common sample.
* Pass numeric variables and optional if or in restrictions.
* Store the paired statistics and observation count for esttab.
program define table2_stats, eclass
    syntax varlist(numeric) [if] [in]
    marksample touse
    quietly count if `touse'
    local n = r(N)
    tempname B
    local names
    foreach v of local varlist {
        quietly summarize `v' if `touse'
        matrix `B' = nullmat(`B'), r(mean), r(sd)
        local names `names' `v'_mean `v'_sd
    }
    matrix colnames `B' = `names'
    ereturn post `B', obs(`n')
end

* Compute the same summary statistics for each of the 11 sectors.
eststo clear
local sectors 10 15 20 25 30 35 40 45 50 55 60
local models
foreach s of local sectors {
    quietly table2_stats reportpages imgc cmic chartc mapc infogc tc if gsector == `s'
    eststo sector`s'
    local models `models' sector`s'
}

* Export the sectors as columns with two rows per variable.
esttab `models' using "Table2-1.rtf", replace ///
    cells(b(fmt(2))) ///
    mtitles("Energy (10)" "Mat. (15)" "Ind. (20)" ///
            "Con. Disc. (25)" "Con. St. (30)" "Health (35)" ///
            "Fin. (40)" "Inf. Tech. (45)" "Com. Ser. (50)" ///
            "Util. (55)" "Real Est. (60)") ///
    varlabels( ///
        reportpages_mean "# Report Pages (Mean)" ///
        reportpages_sd   "# Report Pages (Std. Dev.)" ///
        imgc_mean        "IMGC (Mean)" ///
        imgc_sd          "IMGC (Std. Dev.)" ///
        cmic_mean        "CMIC (Mean)" ///
        cmic_sd          "CMIC (Std. Dev.)" ///
        chartc_mean      "CHARTC (Mean)" ///
        chartc_sd        "CHARTC (Std. Dev.)" ///
        mapc_mean        "MAPC (Mean)" ///
        mapc_sd          "MAPC (Std. Dev.)" ///
        infogc_mean      "INFOGC (Mean)" ///
        infogc_sd        "INFOGC (Std. Dev.)" ///
        tc_mean          "TC (Mean)" ///
        tc_sd            "TC (Std. Dev.)") ///
    stats(N, fmt(%12.0fc) labels("# of Firm-year Obs.")) ///
    nonumbers collabels(none) nonotes nogaps ///
    prehead( ///
        "{\rtf1\ansi\deff0 {\fonttbl\f0\fnil Times New Roman;}" ///
        "\landscape\paperw16838\paperh11906\margl540\margr540\margt720\margb720" ///
        "\deflang1033\plain\fs24" "{") ///
    varwidth(30) modelwidth(7)

capture program drop table2_stats

restore
* Table 3. Annual prevalence of visual categories
* Flag each report's visual categories and count reports by fiscal year.
preserve 
gen n_all = 1
gen n_img = imgc > 0
gen n_t = tc > 0
gen n_cmi = chartc > 0 | mapc > 0 | infogc > 0
gen n_vis = n_img == 1 | n_t == 1 | n_cmi == 1 
collapse (sum) n_all n_vis n_img n_t n_cmi, by(fyear)
sort fyear
* Add an ALL row that sums counts across fiscal years.
insobs 1
local allrow = _N
local countvars n_all n_img n_t n_cmi n_vis
foreach v of local countvars {
    quietly summarize `v' if _n < `allrow', meanonly
    replace `v' = r(sum) in `allrow'
}
tostring fyear, generate(year)
replace year = "ALL" in `allrow'
* Use all reports or visual reports as the denominator, as labeled.
gen double p_vis_all = 100 * n_vis / n_all
gen double p_img_all = 100 * n_img / n_all
gen double p_img_vis = 100 * n_img / n_vis if n_vis > 0
gen double p_t_all = 100 * n_t / n_all
gen double p_t_vis = 100 * n_t / n_vis if n_vis > 0
gen double p_cmi_all = 100 * n_cmi / n_all
gen double p_cmi_vis = 100 * n_cmi / n_vis if n_vis > 0
order year n_all n_vis p_vis_all n_img p_img_all p_img_vis n_t p_t_all p_t_vis n_cmi p_cmi_all p_cmi_vis
* Use fiscal years and the ALL label as the table's row names.
mkmat n_all n_vis p_vis_all ///
      n_img p_img_all p_img_vis ///
      n_t p_t_all p_t_vis ///
      n_cmi p_cmi_all p_cmi_vis, ///
      matrix(Table3) rownames(year)
* Export counts as integers and percentages to one decimal place.
esttab matrix(Table3, fmt(0 0 1 0 1 1 0 1 1 0 1 1)) using "Table3-1.rtf", replace rtf ///
    nomtitles nonumbers noobs nonotes ///
    collabels("# of ALL" "# of VIS" "% VIS of ALL" ///
              "# of IMG" "% IMG of ALL" "% IMG of VIS" ///
              "# of T" "% T of ALL" "% T of VIS" ///
              "# of CMI" "% CMI of ALL" "% CMI of VIS", ///
              lhs("YEAR")) ///
    compress nogaps
restore

* Table 4. Cross-sectional statistics for firm characteristics
preserve
* Use the firm characteristics available in the input dataset.
local vars sizeinmil assetsinmil booktomarket sdret turnover insthold annret roa eg advexptosale analystscoverage
* Average each variable across the firm's nonmissing years.
collapse (mean) `vars', by(gvkey)

label variable sizeinmil       "SizeInMil"
label variable assetsinmil     "AssetsInMil"
label variable booktomarket    "BookToMarket"
label variable sdret           "SdRet"
label variable turnover        "Turnover"
label variable insthold        "InstHold"
label variable annret          "AnnRet"
label variable roa             "ROA"
label variable eg              "EG"
label variable advexptosale    "AdvExpToSale"
label variable analystscoverage "AnalystsCoverage"

* Compute cross-sectional summary statistics for firms with all 11 means available.
eststo clear
estpost summarize `vars', detail listwise
eststo table4

esttab table4 using "Table4-1.rtf", replace ///
    cells("mean(fmt(3)) sd(fmt(3)) p10(fmt(3)) p25(fmt(3)) p50(fmt(3)) p75(fmt(3)) p90(fmt(3))") ///
    collabels("Mean" "Std. Dev." "10%" "25%" "Median" "75%" "90%") ///
    stats(N, fmt(%12.0fc) labels("# of firms")) ///
    label nonumbers nomtitles nonotes nogaps ///
    varwidth(24) modelwidth(10)

restore

* Table 5. Correlations among visual page counts
preserve
* Apply a complete-case screen to the five original page counts.
drop if missing(imgc, chartc, mapc, infogc, tc)
* Winsorize chart, map, and infographic counts at the 1st and 99th percentiles.
* Use the existing imgc_w and tc_w columns for the other two measures.
winsor2  chartc mapc infogc , cuts(1 99) suffix(_w)
label variable imgc_w   "(1) IMGC"
label variable chartc_w "(2) CHARTC"
label variable mapc_w   "(3) MAPC"
label variable infogc_w "(4) INFOGC"
label variable tc_w     "(5) TC"
* Compute correlations on a common sample of the five winsorized measures.
estpost correlate imgc_w chartc_w mapc_w infogc_w tc_w, matrix listwise
esttab . using "Table5-1.rtf", replace ///
    unstack b(2) not nostar noobs ///
    label nonumbers nomtitles nonotes nogaps ///
    eqlabels("(1)" "(2)" "(3)" "(4)" "(5)") ///
    varwidth(20) modelwidth(10)
restore

* Table 6. Firm-year regressions of image page counts
preserve
* Construct the image count lag within firm using the previous consecutive fiscal year.
drop if missing(gvkey) | missing(fyear)
egen long t6_firm_id = group(gvkey)
xtset t6_firm_id fyear
gen double lag_imgc = L.imgc
* Restrict the base sample to fiscal years 2002 through 2019.
keep if base_sample_flag == 1
keep if inrange(fyear, 2002, 2019)
* Identify the continuous controls to winsorize and standardize.
local controls lnassets lnbm insthold advexptosale roa annret sdret turnover ///
    earnings_volatility eg_x_range analystscoverage analystdisp abssue ///
    business_segments geographic_segments

* Optional common-sample screen (disabled). Each regression uses its own eligible observations.
//foreach v in imgc lag_imgc eg `controls' {
    //drop if missing(`v')
//}

* Winsorize the controls at the 1st and 99th percentiles before standardizing.
winsor2 `controls', cuts(1 99) suffix(_w)
foreach v of local controls {
    rename `v'_w w_`v'
}
* Standardize IMGC and its lag in their original scale and controls after winsorization.
foreach v in imgc lag_imgc {
    egen double z_`v' = std(`v')
}
foreach v of local controls {
    egen double z_`v' = std(w_`v')
}

label variable z_lag_imgc "LagDEP (Z)"
label variable z_lnassets "LnAssets (Z)"
label variable z_lnbm "LnBM (Z)"
label variable z_insthold "InstHold (Z)"
label variable z_advexptosale "AdvExpToSale (Z)"
label variable z_roa "ROA (Z)"
label variable z_annret "AnnRet (Z)"
label variable z_sdret "SdRet (Z)"
label variable z_turnover "Turnover (Z)"
label variable z_earnings_volatility "Earnings Volatility (Z)"
label variable eg "EG"
label variable z_eg_x_range "EG x RANGE (Z)"
label variable z_analystscoverage "Analyst Coverage (Z)"
label variable z_analystdisp "Analyst Disp (Z)"
label variable z_abssue "AbsSUE (Z)"
label variable z_business_segments "Business Segments (Z)"
label variable z_geographic_segments "Geographic Segments (Z)"

* Add blocks of controls across the four specifications.
local x1 z_lag_imgc z_lnassets z_lnbm z_insthold z_advexptosale ///
    z_roa z_annret z_sdret z_turnover
local x2 `x1' z_earnings_volatility eg z_eg_x_range
local x3 `x2' z_analystscoverage z_analystdisp z_abssue
local x4 `x3' z_business_segments z_geographic_segments

* Absorb firm and fiscal-year fixed effects and cluster by both dimensions.
eststo clear

reghdfe z_imgc `x1', absorb(t6_firm_id fyear) vce(cluster t6_firm_id fyear)
eststo t6_m1
estadd local YearFE             "Yes"
estadd local FirmFE             "Yes"

reghdfe z_imgc `x2', absorb(t6_firm_id fyear) vce(cluster t6_firm_id fyear)
eststo t6_m2
estadd local YearFE             "Yes"
estadd local FirmFE             "Yes"

reghdfe z_imgc `x3', absorb(t6_firm_id fyear) vce(cluster t6_firm_id fyear)
eststo t6_m3
estadd local YearFE             "Yes"
estadd local FirmFE             "Yes"

reghdfe z_imgc `x4', absorb(t6_firm_id fyear) vce(cluster t6_firm_id fyear)
eststo t6_m4
estadd local YearFE             "Yes"
estadd local FirmFE             "Yes"

* Export coefficients, t statistics, observation counts, and overall R-squared.
esttab t6_m1 t6_m2 t6_m3 t6_m4 using "Table6-1.rtf", replace ///
    b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) ///
    order(`x4') drop(_cons) ///
    mtitles("(1)" "(2)" "(3)" "(4)") nonumbers ///
    stats(FirmFE YearFE N r2, fmt(0 0 %12.0fc 3) ///
        labels("Firm FE" "Year FE" "Observations" "R-squared")) ///
    label nogaps varwidth(28) modelwidth(12) ///
// Restore the firm-year data in memory after exporting the table.
restore
* Table 7. Analyst forecast error regressions by outcome quarter
preserve
import delimited using "Replication/Dinove/analyst_firm_Dinove.csv",clear
* Use the prepared analyst-firm-quarter sample and build fixed-effect and cluster IDs.
egen long firm_id = group(gvkey)
egen long analyst_num = group(analyst_id)
egen long analyst_year = group(analyst_id outcome_fyear)

* Standardize IMGC and TDUM directly. Winsorize the remaining variables before standardizing.
local visual imgc tdum
local continuous chartdum mapdum infogdum wafe reportpages daystoearnann analystdisp insthold ///
    sdret annret roa advexptosale lnassets lnsize lnbm turnover 

* Save a temporary copy so each outcome quarter starts from the same input.
tempfile t7_base
save `t7_base'

* List the regressors in the order used in the output table.
local x z_imgc z_chartdum z_mapdum z_infogdum z_tdum ///
    z_reportpages z_daystoearnann z_analystdisp z_insthold ///
    z_sdret z_annret z_roa z_advexptosale z_lnassets z_lnsize ///
    z_lnbm z_turnover

eststo clear
local inference_note ""

* Estimate one model for each quarter of the next fiscal year.
forvalues q = 1/4 { 
    use `t7_base', clear
    keep if outcome_fqtr == `q'

    * Winsorize at the 1st and 99th percentiles within each outcome quarter.
    foreach v of local continuous {
		winsor2 `v', cuts(1 99) suffix(_w)
		rename `v'_w w_`v'
		
        * Standardize the winsorized values using the quarter-specific mean and standard deviation.
        egen double z_`v' = std(w_`v')
    }

    * Standardize IMGC and TDUM in their original scale within the same quarter.
    foreach v of local visual {
        egen double z_`v' = std(`v')
    }

    label variable z_wafe "WAFE (Z)"
    label variable z_imgc "IMGC (Z)"
    label variable z_chartdum "CHARTDUM (Z)"
    label variable z_mapdum "MAPDUM (Z)"
    label variable z_infogdum "INFOGDUM (Z)"
    label variable z_tdum "TDUM (Z)"
    label variable z_reportpages "# Report Pages (Z)"
    label variable z_daystoearnann "DaysToEarnAnn (Z)"
    label variable z_analystdisp "Analyst DISP (Z)"
    label variable z_insthold "InstHold (Z)"
    label variable z_sdret "SdRet (Z)"
    label variable z_annret "AnnRet (Z)"
    label variable z_roa "ROA (Z)"
    label variable z_advexptosale "AdvExpToSale (Z)"
    label variable z_lnassets "LnAssets (Z)"
    label variable z_lnsize "LnSize (Z)"
    label variable z_lnbm "LnBM (Z)"
    label variable z_turnover "Turnover (Z)"

    * Absorb firm and analyst-by-outcome-year fixed effects. Cluster by analyst and outcome year.
    reghdfe z_wafe `x', absorb(firm_id analyst_year) vce(cluster analyst_num outcome_fyear)
    estadd local FirmFE "YES"
    estadd local AnalystYearFE "YES"
    eststo t7_q`q'
}

* Export the four quarter-specific models with t statistics and overall R-squared.
esttab t7_q1 t7_q2 t7_q3 t7_q4 using "Table7-1.rtf", replace ///
    b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) ///
    order(`x') drop(_cons) mtitles("Q1" "Q2" "Q3" "Q4") ///
    stats(FirmFE AnalystYearFE N r2, fmt(0 0 %12.0fc 3) ///
        labels("Firm FE" "Analyst x Year FE" "Observations" "R-squared")) ///
    label nogaps varwidth(28) modelwidth(12) ///
// Restore the firm-year data in memory after exporting the table.
restore




































