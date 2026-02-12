import tqdm
import torch
import utils.util as util
import os
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def plot_training_progress(train_losses, val_maps, val_precisions, val_recalls, val_map50s, epoch, save_dir):
    """학습 진행 상황을 2x2 subplot으로 시각화하고 저장하는 함수"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
    
    epochs_range = range(1, len(train_losses) + 1)
    
    # 1. Training Loss
    ax1.plot(epochs_range, train_losses, 'b-', linewidth=2, label='Train Loss')
    ax1.set_title('Training Loss', fontsize=14, fontweight='bold')
    ax1.set_xlabel('Epoch')
    ax1.set_ylabel('Loss')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # 2. mAP@0.5:0.95
    ax2.plot(epochs_range, val_maps, 'g-', linewidth=2, label='mAP@0.5:0.95')
    ax2.set_title('Validation mAP@0.5:0.95', fontsize=14, fontweight='bold')
    ax2.set_xlabel('Epoch')
    ax2.set_ylabel('mAP')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    # 3. Precision & Recall
    ax3.plot(epochs_range, val_precisions, 'orange', linewidth=2, label='Precision')
    ax3.plot(epochs_range, val_recalls, 'red', linewidth=2, label='Recall')
    ax3.set_title('Validation Precision & Recall', fontsize=14, fontweight='bold')
    ax3.set_xlabel('Epoch')
    ax3.set_ylabel('Score')
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    
    # 4. mAP@0.5
    ax4.plot(epochs_range, val_map50s, 'purple', linewidth=2, label='mAP@0.5')
    ax4.set_title('Validation mAP@0.5', fontsize=14, fontweight='bold')
    ax4.set_xlabel('Epoch')
    ax4.set_ylabel('mAP@0.5')
    ax4.grid(True, alpha=0.3)
    ax4.legend()
    
    # 전체 제목
    fig.suptitle(f'Training Progress - Epoch {epoch}', fontsize=16, fontweight='bold')
    
    # 최신 값들을 텍스트로 표시
    if len(train_losses) > 0:
        latest_info = f"""Latest Values (Epoch {len(train_losses)}):
Train Loss: {train_losses[-1]:.4f} | mAP@0.5:0.95: {val_maps[-1]:.4f}
Precision: {val_precisions[-1]:.4f} | Recall: {val_recalls[-1]:.4f} | mAP@0.5: {val_map50s[-1]:.4f}
Best mAP@0.5:0.95: {max(val_maps):.4f} (Epoch {val_maps.index(max(val_maps))+1})"""
        
        fig.text(0.02, 0.02, latest_info, fontsize=10, 
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue', alpha=0.8))
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.93, bottom=0.15)
    
    # 저장
    save_path = os.path.join(save_dir, f'training_progress_epoch_{epoch}.png')
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"📈 학습 진행 그래프 저장: {save_path}")
    
    plt.show()
    plt.close()


def visualize_ground_truth_and_prediction_separately(model, dataset, idx=0, conf_threshold=0.1, iou_threshold=0.3, epoch=None, save_dir=None):
    """실제 라벨과 예측 라벨을 subplot으로 좌우에 표시하는 함수"""
    if len(dataset) <= idx:
        print(f"경고: 데이터셋이 비어 있거나 idx {idx}가 데이터셋 크기({len(dataset)})보다 큽니다.")
        return
    
    model.eval()
    img, cls, box, _ = dataset[idx]
    
    # 하나의 figure에 2개의 subplot 생성 (1행 2열)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    img = img.cpu()/255.
    # Subplot 1: Ground Truth (실제 라벨)
    ax1.imshow(img.permute(1, 2, 0).cpu().numpy())
    class_names = {
            0: "Epithelial",
            1: "Stromal",
            2: "Lymphocyte",
            3: "Plasma",
            4: "Neutrophil",
            5: "Eosinophil"
        }
    for i in range(len(cls)):
        class_id = cls[i].item()
        x_center, y_center, w, h = box[i].tolist()
        
        x = (x_center - w/2) * img.shape[2]
        y = (y_center - h/2) * img.shape[1]
        w_box = w * img.shape[2]
        h_box = h * img.shape[1]
        if class_id == 0: #Neutrophil
            color = 'orange'
        elif class_id == 1: #Epithelial
            color = 'green'
        elif class_id == 2: #Lymphocyte
            color = 'red'
        elif class_id == 3: #Plasma
            color = 'skyblue'
        elif class_id == 4: #Eosinophil
            color = 'blue'
        elif class_id == 5: #Connective tissue
            color = 'yellow'
        # 중심점 표시
        # 중심점 좌표 계산
        center_x = int(x + w_box / 2)
        center_y = int(y + h_box / 2)

        ax1.scatter(center_x, center_y, facecolors='none',  s=20, marker='o', edgecolors=color, linewidths=1)

    gt_title = f'Ground Truth '
    if epoch is not None:
        gt_title += f' - Epoch {epoch}'
    ax1.set_title(gt_title, fontsize=16, fontweight='bold')
    ax1.axis('off')
    
    # Subplot 2: Model Prediction (예측 라벨)
    ax2.imshow(img.permute(1, 2, 0).cpu().numpy())
    
    prediction_count = 0
    with torch.no_grad():
        img_input = img.unsqueeze(0).to(device)
        with torch.amp.autocast('cuda'):
            pred = model(img_input)

        # NMS 적용
        results = util.non_max_suppression(pred, confidence_threshold=conf_threshold, iou_threshold=iou_threshold)
        if len(results[0]) > 0:
            for *xyxy, conf, cls_id in results[0]:
                x1, y1, x2, y2 = xyxy
                x1, y1, x2, y2 = x1.item(), y1.item(), x2.item(), y2.item()
                w_pred = x2 - x1
                h_pred = y2 - y1

                if cls_id.item() == 0: #Neutrophil
                    color = 'orange'
                elif cls_id.item() == 1: #Epithelial
                    color = 'green'
                elif cls_id.item() == 2: #Lymphocyte
                    color = 'red'
                elif cls_id.item() == 3: #Plasma
                    color = 'skyblue'
                elif cls_id.item() == 4: #Eosinophil
                    color = 'blue'
                elif cls_id.item() == 5: #Connective tissue
                    color = 'yellow'
                # 중심점 표시
                center_x = (x1 + x2)//2
                center_y = (y1 + y2)//2
                ax2.scatter(center_x, center_y, facecolors='none',  s=20, marker='o', edgecolors=color, linewidths=1)

                prediction_count += 1
        
        if prediction_count == 0:
            ax2.text(img.shape[2]//2, img.shape[1]//2, 'No Predictions', 
                     fontsize=20, color='white', ha='center', va='center',
                     bbox=dict(facecolor='red', alpha=0.8, pad=10))
    
    pred_title = f'Model Prediction - {prediction_count} detections'
    if epoch is not None:
        pred_title += f' - Epoch {epoch}'
    ax2.set_title(pred_title, fontsize=16, fontweight='bold')
    ax2.axis('off')
    
    # 전체 figure 제목 설정
    if epoch is not None:
        fig.suptitle(f'Validation Comparison - Epoch {epoch}, Sample {idx+1}', 
                     fontsize=18, fontweight='bold', y=0.95)
    
    # 범례 추가
    legend_elements = [
        patches.Patch(color='orange', label='Neutrophil'),
        patches.Patch(color='green', label='Epithelial'),
        patches.Patch(color='red', label='Lymphocyte'),
        patches.Patch(color='skyblue', label='Plasma'),
        patches.Patch(color='blue', label='Eosinophil'),
        patches.Patch(color='yellow', label='Connective tissue'),
    ]
    fig.legend(handles=legend_elements, loc='lower center', ncol=3, 
               bbox_to_anchor=(0.5, 0.02), fontsize=12)
    
    # 레이아웃 조정
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.15, top=0.85)
    
    # 저장
    if save_dir and epoch:
        save_path = os.path.join(save_dir, f'validation_comparison_epoch_{epoch}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"✅ 비교 이미지 저장: {save_path}")
    
    # plt.show()
    plt.clf()
    
    
    
def compute_validation_metrics(model, val_loader, device, params):
    """검증 메트릭 계산 함수 (mAP, precision, recall 포함) - loss 계산 제거, 라벨 없는 경우 처리"""
    model.eval()
    
    # Configure IoU thresholds for mAP calculation
    iou_v = torch.linspace(start=0.5, end=0.95, steps=10).to(device)  # iou vector for mAP@0.5:0.95
    n_iou = iou_v.numel()
    
    metrics = []
    
    with torch.no_grad():
        for val_images, val_targets in val_loader:
            val_images = val_images.to(device).float() / 255
            _, _, h, w = val_images.shape  # batch-size, channels, height, width
            scale = torch.tensor((w, h, w, h)).to(device)
            
            # 모델 예측만 수행 (loss 계산 제거)
            with torch.amp.autocast('cuda'):
                val_outputs = model(val_images)
            
            # NMS for metric calculation
            outputs = util.non_max_suppression(val_outputs)
            
            # Metrics calculation
            for i, output in enumerate(outputs):
                idx = val_targets['idx'] == i
                cls = val_targets['cls'][idx]
                box = val_targets['box'][idx]
                
                # 라벨도 없고 예측도 없는 경우 - 완전히 건너뛰기
                if cls.shape[0] == 0 and output.shape[0] == 0:
                    continue
                
                # 라벨은 없지만 예측이 있는 경우 (False Positives)
                if cls.shape[0] == 0 and output.shape[0] > 0:
                    metric = torch.zeros(output.shape[0], n_iou, dtype=torch.bool).to(device)
                    metrics.append((metric, output[:, 4], output[:, 5], torch.tensor([], device=device)))
                    continue
                
                # 라벨은 있지만 예측이 없는 경우 (False Negatives)
                if cls.shape[0] > 0 and output.shape[0] == 0:
                    cls = cls.to(device)
                    metric = torch.zeros(0, n_iou, dtype=torch.bool).to(device)
                    metrics.append((metric, torch.zeros(0).to(device), torch.zeros(0).to(device), cls.squeeze(-1)))
                    continue
                
                # 라벨도 있고 예측도 있는 경우만 정상 처리
                cls = cls.to(device)
                box = box.to(device)
                
                metric = torch.zeros(output.shape[0], n_iou, dtype=torch.bool).to(device)
                
                # Evaluate - cls와 box가 모두 존재하는 경우만 처리
                try:
                    # cls 차원 확인 및 조정
                    if cls.dim() == 1:
                        cls_reshaped = cls.unsqueeze(1)  # [N] -> [N, 1]
                    else:
                        cls_reshaped = cls
                    
                    # box를 xyxy 형식으로 변환
                    box_xyxy = util.wh2xy(box) * scale
                    
                    # target 생성 [N, 5] (class, x1, y1, x2, y2)
                    target = torch.cat(tensors=(cls_reshaped, box_xyxy), dim=1)
                    metric = util.compute_metric(output[:, :6], target, iou_v)
                except Exception as e:
                    print(f"메트릭 계산 중 오류 (건너뛰기): {e}")
                    continue
                
                # Append
                metrics.append((metric, output[:, 4], output[:, 5], cls.squeeze(-1)))
    
    # Calculate mAP if we have metrics
    m_pre, m_rec, map50, mean_ap = 0, 0, 0, 0
    if len(metrics) > 0:
        try:
            # 각 메트릭 요소를 안전하게 결합
            stats = []
            for i in range(4):  # metric, conf, cls_pred, cls_true
                elements = []
                for metric_tuple in metrics:
                    if i < len(metric_tuple) and metric_tuple[i] is not None:
                        element = metric_tuple[i]
                        # 텐서를 numpy로 변환하고 차원 확인
                        if isinstance(element, torch.Tensor):
                            element_np = element.cpu().numpy()
                            # 0차원 텐서를 1차원으로 변환
                            if element_np.ndim == 0:
                                element_np = np.array([element_np])
                            elements.append(element_np)
                        else:
                            elements.append(element)
                
                # 요소들이 있을 때만 concatenate
                if elements:
                    # 모든 요소가 같은 차원인지 확인
                    if all(isinstance(elem, np.ndarray) for elem in elements):
                        try:
                            concatenated = np.concatenate(elements, axis=0)
                            stats.append(concatenated)
                        except ValueError as ve:
                            print(f"Concatenation 오류 (인덱스 {i}): {ve}")
                            stats.append(np.array([]))
                    else:
                        stats.append(np.array([]))
                else:
                    stats.append(np.array([]))
            
            # stats가 올바르게 생성되었는지 확인
            if len(stats) == 4 and all(isinstance(s, np.ndarray) for s in stats):
                tp, fp, m_pre, m_rec, map50, mean_ap = util.compute_ap(*stats, plot=False, names=params["names"])
            else:
                print("메트릭 통계 생성 실패")
                m_pre, m_rec, map50, mean_ap = 0, 0, 0, 0
                
        except Exception as e:
            print(f"mAP 계산 중 오류: {e}")
            print(f"메트릭 개수: {len(metrics)}")
            if len(metrics) > 0:
                print(f"첫 번째 메트릭 구조: {[type(x) for x in metrics[0]]}")
                print(f"첫 번째 메트릭 크기: {[x.shape if hasattr(x, 'shape') else len(x) if hasattr(x, '__len__') else 'scalar' for x in metrics[0]]}")
            m_pre, m_rec, map50, mean_ap = 0, 0, 0, 0
    
    return m_pre, m_rec, map50, mean_ap


def compute_validation_metrics_with_kappa(model, val_loader, device, params):
    """Cohen's Kappa를 포함한 검증 메트릭 계산"""
    try:
        from sklearn.metrics import cohen_kappa_score
    except ImportError:
        print("경고: scikit-learn이 설치되지 않아 Cohen's Kappa를 계산할 수 없습니다.")
        precision, recall, map50, mean_ap = compute_validation_metrics(model, val_loader, device, params)
        return precision, recall, map50, mean_ap, 0.0
    
    # 기본 메트릭 계산
    precision, recall, map50, mean_ap = compute_validation_metrics(model, val_loader, device, params)
    
    # Cohen's Kappa 계산을 위한 grid 기반 비교
    model.eval()
    grid_size = 16  # 16x16 grid로 이미지 분할
    all_gt_labels = []
    all_pred_labels = []
    
    with torch.no_grad():
        for batch_idx, (images, targets) in enumerate(val_loader):
            images = images.to(device).float() / 255
            
            # 예측
            with torch.amp.autocast('cuda'):
                pred = model(images)
            
            # NMS 적용
            results = util.non_max_suppression(pred, confidence_threshold=0.1, iou_threshold=0.3)

            # 각 이미지에 대해 grid 기반 라벨링
            for i in range(len(images)):
                gt_grid = np.zeros((grid_size, grid_size), dtype=int)  # 0: 배경, 1: negative, 2: positive
                pred_grid = np.zeros((grid_size, grid_size), dtype=int)
                
                # Ground truth 처리
                cls_targets = targets['cls']
                box_targets = targets['box']
                idx_targets = targets['idx']
                
                # 해당 이미지의 타겟만 필터링
                batch_mask = idx_targets == i
                if batch_mask.any():
                    batch_cls = cls_targets[batch_mask]
                    batch_box = box_targets[batch_mask]
                    
                    for cls, box in zip(batch_cls, batch_box):
                        x_center, y_center = box[0].item(), box[1].item()
                        grid_x = min(int(x_center * grid_size), grid_size - 1)
                        grid_y = min(int(y_center * grid_size), grid_size - 1)
                        gt_grid[grid_y, grid_x] = cls.item() + 1  # 0→1, 1→2
                
                # Predictions 처리
                if len(results) > i and len(results[i]) > 0:
                    for *xyxy, conf, cls_id in results[i]:
                        x1, y1, x2, y2 = xyxy
                        x_center = ((x1 + x2) / 2).item() / 512  # 정규화
                        y_center = ((y1 + y2) / 2).item() / 512
                        
                        grid_x = min(int(x_center * grid_size), grid_size - 1)
                        grid_y = min(int(y_center * grid_size), grid_size - 1)
                        pred_grid[grid_y, grid_x] = cls_id.item() + 1
                
                all_gt_labels.extend(gt_grid.flatten())
                all_pred_labels.extend(pred_grid.flatten())
    
    # Cohen's Kappa 계산
    try:
        if len(all_gt_labels) > 0 and len(all_pred_labels) > 0:
            kappa = cohen_kappa_score(all_gt_labels, all_pred_labels)
        else:
            kappa = 0.0
    except Exception as e:
        print(f"Cohen's Kappa 계산 오류: {e}")
        kappa = 0.0
    
    return precision, recall, map50, mean_ap, kappa


def get_kappa_interpretation(kappa):
    """Kappa 값 해석"""
    if kappa < 0: 
        return "Poor"
    elif kappa < 0.21: 
        return "Slight"
    elif kappa < 0.41: 
        return "Fair"  
    elif kappa < 0.61: 
        return "Moderate"
    elif kappa < 0.81: 
        return "Substantial"
    else: 
        return "Almost Perfect"


def quick_kappa_test(model, val_loader, device):
    """현재 모델의 Cohen's Kappa 빠른 측정"""
    try:
        from sklearn.metrics import cohen_kappa_score
    except ImportError:
        print("경고: scikit-learn이 설치되지 않아 Cohen's Kappa를 계산할 수 없습니다.")
        return 0.0
        
    model.eval()
    
    # 몇 개 샘플로 빠른 테스트
    sample_gt = []
    sample_pred = []
    
    with torch.no_grad():
        for i, (images, targets) in enumerate(val_loader):
            if i >= 10:  # 10개 배치만 테스트
                break
                
            images = images.to(device).float() / 255
            pred = model(images)
            results = util.non_max_suppression(pred, confidence_threshold=0.25, iou_threshold=0.45)
            
            # 간단한 비교를 위해 객체 개수 기반 라벨링
            gt_count = len(targets['cls'])
            pred_count = len(results[0]) if len(results) > 0 and len(results[0]) > 0 else 0
            
            # 단순화된 라벨 (0: 없음, 1: 적음, 2: 많음)
            gt_label = 0 if gt_count == 0 else (1 if gt_count <= 5 else 2)
            pred_label = 0 if pred_count == 0 else (1 if pred_count <= 5 else 2)
            
            sample_gt.append(gt_label)
            sample_pred.append(pred_label)
    
    try:
        if len(sample_gt) > 0 and len(sample_pred) > 0:
            quick_kappa = cohen_kappa_score(sample_gt, sample_pred)
        else:
            quick_kappa = 0.0
    except Exception as e:
        print(f"빠른 Kappa 계산 오류: {e}")
        quick_kappa = 0.0
    
    print(f"📊 빠른 Cohen's Kappa 측정: {quick_kappa:.4f} ({get_kappa_interpretation(quick_kappa)})")
    return quick_kappa