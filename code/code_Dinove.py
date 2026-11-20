
# %% Collect annual report links
# Construct annual report visual measures with DINOv3 for the S&P 1500 target sample.
#
# Main inputs
#   sp1500_raw.csv           S&P 1500 tickers and Compustat GVKEYs
#   Stocklight               Company listings and annual report PDF links
#   combined_annotations.csv and images/   Manual labels and matching crop images
#
# Main outputs
#   sp1500_stocklight_pdf_urls_v4.csv  Report links and firm identifiers
#   regions.csv                       Detected regions and crop paths
#   dinov3_finetuned/                 Checkpoint, image processor, and evaluation files
#   classified_dinov3.csv             Predicted class and confidence for each crop
#   page_category_dinov3.csv          Dominant class per page with a retained crop
#   company_year_counts_dinov3.csv    Page counts by firm, report year, and visual class

import subprocess
import json
import time
from urllib.parse import urlsplit
import pandas as pd  
import re
from pathlib import Path

# Source = "https://stocklight.com/stocks/us/annual-reports?sort_by=alpha"  # Start from the first listing page.
Source = "https://stocklight.com/stocks/us/annual-reports?sort_by=alpha&page=395&limit=10"
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"

INPUT = ROOT / "sp1500_raw.csv"
OUTPUT = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"

# Evaluate JavaScript in the active Chrome tab through AppleScript.
# js is the expression to evaluate. retries caps the total attempts when Chrome times out.
# Return the result as stripped text.
def chrome_js(js, retries=1):
    script = (
        'tell application "Google Chrome" to '
        'execute active tab of front window javascript '
        + json.dumps(js)
    )

    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True,
                timeout=45
            )
            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            if attempt == retries:
                raise

            print(f"Chrome 暂未返回结果，5 秒后重试（{attempt + 1}/{retries}）。")
            time.sleep(5)

        except subprocess.CalledProcessError as error:
            print("AppleScript 详细错误：", error.stderr)
            raise

# Poll the active tab until the JavaScript condition evaluates to true.
def wait_for_page(condition):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = chrome_js(f"({condition}) ? 'READY' : 'WAIT'",retries=3)
        if status == "READY":
            return
        time.sleep(1)
    raise TimeoutError("网页未准备好，请检查 Chrome 当前页面。")

# Open a URL in the same active tab used for JavaScript queries.
def open_url(url):
    script = ('tell application "Google Chrome" to ''set URL of active tab of front window to '+ json.dumps(url))
    subprocess.run(["osascript", "-e", script],capture_output=True,text=True,check=True,timeout=45)

    time.sleep(5)
subprocess.run(["open", "-a", "Google Chrome", Source])
# Identify the company detail links labeled "More".
more_js = ("Array.from(document.querySelectorAll('a[href]'))"".filter(a => a.textContent.trim().toLowerCase() === 'more')")
# Normalize the ticker list to match the company URLs against the target sample.
SP1500 = pd.read_csv(INPUT, dtype=str, keep_default_na=False)
target_tics = set(SP1500["tic"].str.strip().str.upper().str.replace(".", "-", regex=False))
records = []
list_url = Source
# Limit the number of listing pages processed from the configured start URL.
max_pages = 2
pages_done = 0

while list_url is not None:
    # Wait for the expected listing URL and company links before collecting reports.
    for attempt in range(1, 4):
        try:
            wait_for_page(
                f"location.href === {json.dumps(list_url)}"
                f" && ({more_js}).length > 0"
            )

            break

        except TimeoutError:
            # Use the title and page body to identify the site's "Retry later" response.
            text = chrome_js(
                "document.title + ' ' + "
                "(document.body ? document.body.innerText : '')"
            ).lower()

            if "retry later" not in text:
                raise

            if attempt == 3:
                raise TimeoutError(
                    f"该页多次显示 Retry later，请稍后再运行：{list_url}"
                )

            # Back off for 60 seconds before the first retry and 120 before the second.
            delay = 60 * (2 ** (attempt - 1))
            print(f"页面要求稍后重试，等待 {delay} 秒后重新打开同一页。")
            time.sleep(delay)

            open_url(list_url)

    # Read the company URLs and next-page link before leaving the current listing.
    more_urls = json.loads(chrome_js(f"JSON.stringify(({more_js}).map(a => a.href))"))
    next_links = json.loads(chrome_js("JSON.stringify(Array.from(document.querySelectorAll('a[href]')).filter(a => a.textContent.trim() === '>').map(a => a.href))"))
    next_url = next_links[0] if next_links else None
    for i, url in enumerate(more_urls, start=1):
        # Extract the ticker from the company URL and visit only target companies.
        company_code = urlsplit(url).path.strip("/").split("/")[2]
        tic = company_code.split("-", 1)[1].upper()
        if tic.replace(".", "-") not in target_tics:
            continue
        print(f"{tic} 在目标名单中，准备提取年报。")
        records = []
        open_url(url)
        # Confirm that the active tab is on the target company's annual report page.
        wait_for_page(
            f"location.origin === new URL({json.dumps(url)}).origin"
            f" && location.pathname === new URL({json.dumps(url)}).pathname"
            " && document.querySelector('h1')"
            " && document.querySelector('h1').textContent"
            ".toLowerCase().includes('annual reports')"
        )
        # Keep distinct PDF URLs and extract the report year from each filename.
        links = json.loads(chrome_js("JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a => a.href))"))
        pdf_urls=[]
        for link in links:
            if urlsplit(link).path.lower().endswith(".pdf") and link not in pdf_urls:
                pdf_urls.append(link)
        for pdf_url in pdf_urls:
            filename = urlsplit(pdf_url).path.split("/")[-1]
            year_match = re.search(r"-(19\d{2}|20\d{2})-", filename)
            if year_match is None:
                continue
            year = year_match.group(1)
            records.append({"tic": tic, "year": year, "pdf_url": pdf_url})
        df = pd.DataFrame(records, columns=["tic", "year", "pdf_url"])
        if not df.empty:
            # Append report records and deduplicate by ticker and PDF URL.
            df.to_csv(OUTPUT,mode="a",header=not OUTPUT.exists(),index=False,encoding="utf-8" if OUTPUT.exists() else "utf-8-sig")
            all_df = pd.read_csv(OUTPUT, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            all_df = all_df.drop_duplicates(subset=["tic", "pdf_url"])
            all_df.to_csv(OUTPUT, mode="w", index=False, encoding="utf-8-sig")    

        time.sleep(3)

    print("当前列表页的公司已处理完成。")
    pages_done += 1

    list_url = next_url

    if pages_done >= max_pages:
        print(f"已完成 {pages_done} 页，停止采集。")
        break

    list_url = next_url
    time.sleep(3)
    chrome_js(f"location.assign({json.dumps(list_url)}); 'OPENED';")
    print("准备读取下一页：", list_url)


# %% Attach Compustat GVKEYs to annual report links
import pandas as pd
# Read firm identifiers as text to preserve leading zeros in GVKEYs.
companies = pd.read_csv(ROOT / "sp1500_raw.csv",dtype=str,keep_default_na=False)
output_file = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"
reports = pd.read_csv(output_file,dtype=str,keep_default_na=False)
# Apply the same ticker normalization to both files.
companies["tic"] = companies["tic"].str.strip().str.upper().str.replace(".", "-", regex=False)
reports["tic"] = reports["tic"].str.strip().str.upper().str.replace(".", "-", regex=False)
# Build a crosswalk from distinct ticker and GVKEY pairs with nonblank tickers.
mapping = companies[["tic", "gvkey"]].copy()
mapping = mapping[mapping["tic"] != ""]
mapping = mapping.drop_duplicates(subset=["tic", "gvkey"])
# Keep all report records and require at most one crosswalk row per ticker.
reports = reports.merge(mapping,on="tic",how="left",validate="many_to_one")
print("年报记录数：", len(reports))
print("未匹配到 gvkey 的记录数：", reports["gvkey"].isna().sum())
reports.to_csv(output_file, index=False, encoding="utf-8-sig")
print("已保存：", output_file)

# %% Read the annual report URL list
from pathlib import Path
import pandas as pds
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
csv_path = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"
get_PDF_URL = pds.read_csv(csv_path, keep_default_na=False)["pdf_url"]
get_PDF_URL = get_PDF_URL [get_PDF_URL != ""]
# print(get_PDF_URL.head(20))
# print(len(get_PDF_URL))
# for url in get_PDF_URL:
    # print(url)

# %% Render annual report PDFs as PNG files
# Store rendered pages and layout results in separate firm-year folders.
year = 2025
PNG_ROOT = ROOT / "annualreport——png"
get_firm = pds.read_csv(csv_path, dtype = str,keep_default_na=False)["gvkey"].drop_duplicates()
for i in get_firm:
    year_folder = PNG_ROOT / f"{year}"
    company_folder = year_folder  / f"{year}_{i}"
    company_folder.mkdir(parents=True, exist_ok=True)
    year_folder_cropped_result = PNG_ROOT / f"{year}_cropped_result"
    year_folder_cropped_result.mkdir(parents=True, exist_ok=True)
    company_result_folder = year_folder_cropped_result/f"{year}_{i}"
    company_result_folder.mkdir(parents=True, exist_ok=True)
import pymupdf
import requests
reports = pds.read_csv(csv_path, dtype=str, keep_default_na=False)
# Render reports for the configured year when a PDF URL is available.
reports = reports[(reports["year"].str.strip() == str(year))& (reports["pdf_url"].str.strip() != "")]
for report_number,company in enumerate(reports.to_dict("records"), start=1):
    url = company["pdf_url"]
    gvkey = company["gvkey"]
    print(f"目前处理 {report_number}/{len(reports)} 份报告，gvkey：{gvkey}")
    company_folder =  year_folder / f"{year}_{gvkey}"
    # Reuse cached pages if the firm-year folder already contains a PNG file.
    if any(company_folder.glob("*.png")):
        print("已有图片，跳过：", gvkey)
        continue
    try:
        response = requests.get(url, timeout=(10, 60))
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        print("跳过：", url, error)
        continue
    # response = requests.get(url,timeout = (10,60))
    # response.raise_for_status()
    # Open the downloaded PDF in memory and render each page at 200 dpi.
    with pymupdf.open(stream = response.content, filetype = "pdf") as doc:
        for page_number, page in enumerate(doc,start = 1):
             pix = page.get_pixmap(dpi=200,alpha=False)
             # print(doc.page_count)
             # print(pix.width,pix.height)
             image_path = company_folder / f"page_{page_number:04d}.png"
             pix.save(str(image_path))

# %% Detect and crop visual regions
# Save annotated pages, detection JSON files, cropped images, and per-page region records.
from paddleocr import LayoutDetection
from PIL import Image 
model = LayoutDetection(model_name="PP-DocLayout_plus-L",device="cpu")
company_gvkey = pds.read_csv(csv_path,dtype=str, keep_default_na=False)["gvkey"].drop_duplicates()
fields = [ "year", "gvkey", "page_file", "region_number","label", "score", "crop_path"]
# Use the GVKEY position in the report manifest to resume detection.
start_company = 150
for company_number, test_gvkey in enumerate(company_gvkey, start=1):
    if company_number < start_company:
        continue
    print(f"目前处理公司 {company_number}/{len(company_gvkey)}，gvkey：{test_gvkey}")
    test_folder = year_folder / f"{year}_{test_gvkey}"
    image_files = sorted(test_folder.glob("page_*.png"))
    company_result_folder = year_folder_cropped_result / f"{year}_{test_gvkey}"
    company_result_folder.mkdir(parents=True, exist_ok=True)
    for page_path in image_files:
        results = model.predict(str(page_path),batch_size =1 )
        for result in results:
            # Save the layout overlay and structured detections for the page.
            result.save_to_img(save_path=str(company_result_folder))
            result.save_to_json(save_path=str(company_result_folder / f"{page_path.stem}.json"))
            region_records = []
            # Crop only image, chart, and table detections from the original page.
            with Image.open(page_path) as page_image:
                for region_number, box in enumerate(result["boxes"], start=1):
                    if box["label"] in ["image", "chart", "table"]:
                        x1, y1, x2, y2 = map(int, box["coordinate"])
                        cropped_image = page_image.crop((x1, y1, x2, y2))
                        crop_path = company_result_folder / f"{page_path.stem}_{box['label']}_{region_number:03d}.png"
                        cropped_image.save(crop_path)
                        print("已保存：", crop_path)
                        region_records.append({"year": year,"gvkey": test_gvkey,"page_file": page_path.name,
                        "region_number": region_number,"label": box["label"],"score": float(box["score"]),"crop_path": str(crop_path)})
            # Record the detector label, confidence, and path for each retained crop.
            region_df = pds.DataFrame(region_records,columns=fields)
            records_path = company_result_folder/f"{page_path.stem}_regions.csv"
            region_df.to_csv(records_path, index=False, encoding="utf-8-sig")
# %% Combine page-level region manifests
# Combine the selected year's per-page CSVs and keep GVKEYs as text.
csv_combined_result = sorted(year_folder_cropped_result.glob(f"{year}_*/page_*_regions.csv"))
page_tables = []
for csv_path in csv_combined_result:
    page_df = pds.read_csv(csv_path, dtype={"gvkey": str})
    page_tables.append(page_df)
company_regions = pds.concat(page_tables, ignore_index=True)
summary_path = year_folder_cropped_result / "regions.csv"
company_regions.to_csv(summary_path, index=False, encoding="utf-8-sig")

# %% Split the manually labeled crops
from pathlib import Path
import pandas as pds
import hashlib
from PIL import Image
from sklearn.model_selection import train_test_split
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
# Read manual labels, drop blank labels, and resolve sample IDs to PNG paths.
label_file = ROOT / "combined_annotations.csv"
data = pds.read_csv(label_file, dtype=str,  keep_default_na=False)
data["label"] = data["label"].str.strip()
data = data[data["label"] != ""]
data["sample_id"]=data["sample_id"].str.strip()
image_folder = ROOT/"images"
data["image_path"] = data["sample_id"].map(lambda sample_id:str(image_folder/f"{sample_id}.png"))
# Split the crops into 70% training, 15% validation, and 15% test, stratified by class.
train_data, remaining_data = train_test_split(data,test_size=0.3,random_state=123,stratify=data["label"])
validation_data, test_data = train_test_split(remaining_data,test_size=0.50,random_state=42,stratify=remaining_data["label"])
# Save the split manifests before assigning numeric class IDs in memory.
split_folder = label_file.parent / "dinove_splits"
split_folder.mkdir(parents=True, exist_ok=True)
train_data.to_csv(split_folder / "dinove_train.csv", index=False, encoding="utf-8-sig")
validation_data.to_csv(split_folder / "validation.csv", index=False, encoding="utf-8-sig")
test_data.to_csv(split_folder / "dinove_test.csv", index=False, encoding="utf-8-sig")
# Build one class mapping from the sorted training labels and apply it to every split.
class_names = sorted(train_data["label"].unique())
label2id = {name: number for number, name in enumerate(class_names)}
id2label = {number: name for name, number in label2id.items()}
for dataset in [train_data, validation_data, test_data]:
    dataset["label_id"] = dataset["label"].map(label2id).astype(int)
print("类别编号：", label2id)
print(train_data[["sample_id", "label", "label_id"]].head(10))

# %% Build the DINOv3 image datasets
from torch.utils.data import Dataset
from PIL import Image
from transformers import AutoImageProcessor
model_id = "facebook/dinov3-vitb16-pretrain-lvd1689m"
processor = AutoImageProcessor.from_pretrained(model_id)
# Read one crop from the dataset by row position.
# Return the processed RGB image tensor and its human-assigned class ID.
def read_image(dataset, index):
    sample = dataset.iloc[index]
    with Image.open(sample["image_path"]) as image:
        image = image.convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
    pixel_values = inputs["pixel_values"][0]
    label_id = int(sample["label_id"])
    return pixel_values, label_id
# Adapt each data split to the image and label fields expected by the classifier.
class ReportImageDataset(Dataset):
    def __init__(self, data):
        self.data = data
    def __len__(self):
        return len(self.data)
    def __getitem__(self, index):
        pixel_values, label_id = read_image(self.data, index)
        return {"pixel_values": pixel_values,"labels": label_id}
train_dataset = ReportImageDataset(train_data)
validation_dataset = ReportImageDataset(validation_data)
test_dataset = ReportImageDataset(test_data)
print("训练集图片数量：", len(train_dataset))
print("验证集图片数量：", len(validation_dataset))
print("测试集图片数量：", len(test_dataset))

# %% Configure training and evaluation batches
from torch.utils.data import DataLoader

batch_size = 8
# Shuffle the training split and preserve row order for evaluation.
train_loader = DataLoader(train_dataset,batch_size=batch_size,shuffle=True,num_workers=0)
validation_loader = DataLoader(validation_dataset,batch_size=batch_size,shuffle=False,num_workers=0)
test_loader = DataLoader(test_dataset,batch_size=batch_size,shuffle=False,num_workers=0)
# Check the first training batch for the expected image and label tensor shapes.
batch = next(iter(train_loader))
print("图片张量形状：", batch["pixel_values"].shape)
print("标签张量形状：", batch["labels"].shape)
print("这一批的正确标签：", batch["labels"])

# %% Initialize the pretrained DINOv3 classifier
import torch
from torch import nn
from transformers import AutoModel
from transformers.modeling_outputs import ImageClassifierOutput
from sklearn.metrics import accuracy_score, f1_score
from sklearn.metrics import classification_report, confusion_matrix
torch.manual_seed(42)
# Pair the pretrained DINOv3 encoder with a linear head for the labeled classes.
class DINOv3Classifier(nn.Module):
    def __init__(self, model_id, label2id, id2label):
        super().__init__()
        self.vision_model = AutoModel.from_pretrained(model_id)
        self.config = self.vision_model.config
        self.config.num_labels = len(label2id)
        self.config.label2id = label2id
        self.config.id2label = id2label
        self.classifier = nn.Linear(self.config.hidden_size,self.config.num_labels)
    def forward(self, pixel_values, labels=None):
        # Map the pooled image representation to one score per class.
        outputs = self.vision_model(pixel_values=pixel_values)
        features = outputs.pooler_output
        logits = self.classifier(features)
        # Compute cross-entropy when ground-truth labels are supplied.
        loss = None
        if labels is not None:
            loss = nn.functional.cross_entropy(logits, labels)
        return ImageClassifierOutput(loss=loss, logits=logits)
# Select CUDA, Apple MPS, or CPU in that order.
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")
print("使用设备：", device)
model = DINOv3Classifier(model_id, label2id, id2label)
# Freeze the pretrained encoder, then unfreeze its final two Transformer layers.
for parameter in model.vision_model.parameters():
    parameter.requires_grad = False
# Locate the encoder layers on either supported model layout.
if hasattr(model.vision_model, "layer"):
    last_layers = model.vision_model.layer[-2:]
else:
    last_layers = model.vision_model.model.layer[-2:]
for parameter in last_layers.parameters():
    parameter.requires_grad = True
model = model.to(device)
# Use a lower learning rate for the unfrozen encoder layers than for the new head.
optimizer = torch.optim.AdamW([{"params": last_layers.parameters(), "lr": 1e-5},{"params": model.classifier.parameters(), "lr": 1e-3}])
epochs = 3
class_ids = list(range(len(class_names)))
save_folder = ROOT / "dinov3_finetuned"
save_folder.mkdir(parents=True, exist_ok=True)

# %% Define the evaluation routine
# Run DINOv3 inference on the supplied loader without updating the model.
# Return the true and predicted class IDs in loader order for scoring.
def evaluate(loader):
    model.eval()
    true_labels = []
    predicted_labels = []
    with torch.no_grad():
        for batch in loader:
            pixels = batch["pixel_values"].to(device)
            outputs = model(pixel_values=pixels)
            predictions = outputs.logits.argmax(dim=1)
            true_labels.extend(batch["labels"].tolist())
            predicted_labels.extend(predictions.cpu().tolist())
    return true_labels, predicted_labels


# %% Train DINOv3 and select the best checkpoint
best_f1 = -1
history = []

for epoch in range(1, epochs + 1):
    model.train()
    total_loss = 0
    total_images = 0

    for step, batch in enumerate(train_loader, start=1):
        pixels = batch["pixel_values"].to(device)
        labels = batch["labels"].to(device)

        # Clear accumulated gradients before the batch update.
        optimizer.zero_grad()
        outputs = model(pixel_values=pixels, labels=labels)
        loss = outputs.loss
        loss.backward()
        optimizer.step()

        # Weight each batch loss by its image count to compute the mean loss per image.
        image_count = labels.size(0)
        total_loss += loss.item() * image_count
        total_images += image_count
        if step == 1 or step % 10 == 0 or step == len(train_loader):
            print(f"训练 {epoch}/{epochs} 轮，"f"批次 {step}/{len(train_loader)}，"f"本批损失 {loss.item():.4f}",flush=True)
    train_loss = total_loss / total_images
    # Measure validation accuracy and macro F1 at the end of the epoch.
    true_labels, predicted_labels = evaluate(validation_loader)
    val_accuracy = accuracy_score(true_labels, predicted_labels)
    val_f1 = f1_score(true_labels, predicted_labels,labels=class_ids, average="macro", zero_division=0)
    print(f"第 {epoch} 轮完成：训练损失={train_loss:.4f}，"f"验证准确率={val_accuracy:.4f}，验证 Macro F1={val_f1:.4f}")
    # Record the metrics by epoch and save the checkpoint with the highest validation macro F1.
    history.append({"epoch": epoch,"train_loss": train_loss, "validation_accuracy": val_accuracy,"validation_macro_f1": val_f1})
    pds.DataFrame(history).to_csv(save_folder / "training_history.csv",index=False, encoding="utf-8-sig")
    if val_f1 > best_f1:
        best_f1 = val_f1
        torch.save({"model_state_dict": model.state_dict(),"model_id": model_id,"label2id": label2id,"id2label": id2label}, save_folder / "best_model.pt")
        processor.save_pretrained(save_folder)
        print("已保存最佳 DINOv3 模型。")

# %% Evaluate the best checkpoint on the test split
del optimizer
del model
# Rebuild the classifier from the saved model ID and label mapping, then restore its weights.
checkpoint = torch.load(save_folder / "best_model.pt",map_location="cpu",weights_only=True)
model = DINOv3Classifier(checkpoint["model_id"],checkpoint["label2id"],checkpoint["id2label"])
model.load_state_dict(checkpoint["model_state_dict"])
model = model.to(device)
model.eval()
true_labels, predicted_labels = evaluate(test_loader)
print("测试集准确率：", accuracy_score(true_labels, predicted_labels))
print(classification_report(
    true_labels,
    predicted_labels,
    labels=class_ids,
    target_names=class_names,
    zero_division=0
))
# Save one predicted class and a correctness flag for each held-out crop.
test_results = test_data.copy()
test_results["predicted_label_id"] = predicted_labels
test_results["predicted_label"] = test_results["predicted_label_id"].map(id2label)
test_results["correct"] = test_results["label_id"] == test_results["predicted_label_id"]
test_results.to_csv(save_folder / "test_predictions.csv",index=False, encoding="utf-8-sig")
# Write the confusion matrix with true classes in rows and predicted classes in columns.
matrix = confusion_matrix(true_labels, predicted_labels, labels=class_ids)
pds.DataFrame(matrix, index=class_names, columns=class_names).to_csv(save_folder / "confusion_matrix.csv",index_label="true_label", encoding="utf-8-sig")
print("模型和结果已保存到：", save_folder)



# %% Classify report regions and construct visual measures
import torch
import pandas as pds
from transformers import AutoImageProcessor
save_folder = ROOT / "dinov3_finetuned"
# Restore the best classifier and use the image processor saved with it.
checkpoint = torch.load(save_folder / "best_model.pt",map_location="cpu",weights_only=True)
model = DINOv3Classifier(checkpoint["model_id"],checkpoint["label2id"],checkpoint["id2label"])
model.load_state_dict(checkpoint["model_state_dict"])
model = model.to(device)
model.eval()
processor = AutoImageProcessor.from_pretrained(save_folder)
print("微调后的 DINOv3 模型加载成功")
from pathlib import Path
from PIL import Image 
# Read crop records for the inference year. A region manifest for that year must already exist.
year = 2019
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
PNG_ROOT = ROOT / "annualreport——png"
regions_csv = PNG_ROOT/f"{year}_cropped_result"/"regions.csv"
df = pds.read_csv(regions_csv,dtype=str, keep_default_na=False)
classify_result = []
for test_path, company_gvkey in zip(df["crop_path"], df["gvkey"]):
    # Record crop dimensions in pixels before preprocessing the image for DINOv3.
    with Image.open(test_path) as image:
        width, height = image.size
        test_image_rgb = image.convert("RGB")
        inputs = processor(images=test_image_rgb,return_tensors="pt").to(device)
    # Predict the crop's visual class and record its highest softmax probability.
    with torch.no_grad():
        outputs = model(**inputs)
    scores = torch.softmax(outputs.logits, dim=1)[0]
    best_index = scores.argmax().item()
    highest_score = scores[best_index].item()
    predicted_category = model.config.id2label[best_index]
    area = width * height
    print("预测类别：", predicted_category)
    print(f"最高概率：{highest_score:.4f}")
    classify_result.append({"year": year,"gvkey": company_gvkey,"crop_path": str(test_path),"region_areas": area,"predicted_category": predicted_category,"classification_score": highest_score})
classify_df = pds.DataFrame(classify_result)
classify_df["page_file"] = (classify_df["crop_path"].str.extract(r"(page_\d+)_", expand=False)+ ".png")
classify_df_path = PNG_ROOT/f"{year}_cropped_result"/"classified_dinov3.csv"
classify_df.to_csv(classify_df_path,index=False,encoding="utf-8-sig")
# print("Saved:", classify_df_path)

# Keep the seven visual classes for aggregation, excluding Other.
visual_categories = ["Image", "Team", "Chart", "Map", "Infographic","Logo","Table"]
visual_regions = classify_df[classify_df["predicted_category"].isin(visual_categories)].copy()
# Sum crop areas in square pixels by firm, report year, page, and predicted class.
page_category_areas = (visual_regions.groupby(["year", "gvkey", "page_file", "predicted_category"])["region_areas"].sum().reset_index(name="category_area"))
# Assign each page to the class with the largest total crop area.
max_region_rows = (page_category_areas.loc[page_category_areas.groupby(["year", "gvkey", "page_file"])["category_area"].idxmax()].reset_index(drop=True))
page_category_path = PNG_ROOT/f"{year}_cropped_result"/"page_category_dinov3.csv"
max_region_rows.to_csv(page_category_path,index=False,encoding="utf-8-sig")

# Count pages by firm and report year, with one column per visual class.
company_year_counts = (max_region_rows.groupby(["year", "gvkey", "predicted_category"]).size().unstack(fill_value=0).reindex(columns=visual_categories, fill_value=0).reset_index())
company_year_path = (PNG_ROOT / f"{year}_cropped_result" / "company_year_counts_dinov3.csv")
company_year_counts.to_csv(company_year_path,index=False,encoding="utf-8-sig")