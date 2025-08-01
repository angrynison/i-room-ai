# safetyGear/camera_stream.py
import cv2
import time
from safetyGear.utils import detect_and_draw
from safetyGear.alert_service import send_alert
from deep_sort_realtime.deepsort_tracker import DeepSort

cap = cv2.VideoCapture(0)   # 웹캠

# 필수 안전 보호구
REQUIRED_ITEMS = {"safety_harness_on", "safety_lanyard_on", "safety_helmet_on"}

last_alert_time = 0 # 마지막 전송 시각

# DeepSORT 설정
tracker = DeepSort(
    max_age = 30,   # 30프레임 동안 detection 없으면 track 삭제
    n_init = 3,     # 3번 연속 detection 되어야 track 확정
    max_iou_distance = 0.7
)

# 웹캠 프레임을 계속 읽어 스트리밍 + 알림 처리하는 제너레이터
def generate_frames():
    global last_alert_time

    while True:
        # 웹캠에서 프레임 한 장 읽기
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] 프레임을 읽을 수 없습니다.")
            break   # 카메라가 꺼지거나 오류 발생 시 종료

        # YOLO 탐지 실행 -> 객체 감지 후 Bounding Box를 그린 프레임과 감지 정보 반환
        frame, detections, detected_classes = detect_and_draw(frame)

        # detections 리스트를 DeepSORT 입력 형식으로 변환
        ds_detections = []
        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            w, h = x2 - x1, y2 - y1
            ds_detections.append(([x1, y1, w, h],
                                  det["confidence"],
                                  det["class"]))
            
        # DeepSORT tracking
        tracks = tracker.update_tracks(ds_detections, frame=frame)

        # tracking 결과 화면에 표시
        for t in tracks:
            if not t.is_confirmed():
                continue

            x1, y1, x2, y2 = map(int, t.to_ltrb())
            track_id = t.track_id
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(frame, f"ID:{track_id}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # 미착용 여부 판단
        # 필수 보호구(required_items) - 실제 감지된 보호구(detected_classes)
        # 차집합을 구해 누락된 보호구가 있으면 missing에 들어감
        missing = REQUIRED_ITEMS - detected_classes
        
        current_time = time.time()  # 현재 시간

        if missing and (current_time - last_alert_time >= 5):   # 5초 이상 지난 경우에만 전송
            # 누락된 보호구가 있을 경우, 프레임 이미지를 JPEG 바이트로 변환
            _, img_bytes = cv2.imencode(".jpg", frame)

            # 서버로 알림 전송 (이미지 + 누락 정보)
            send_alert(img_bytes.tobytes(), missing)

            last_alert_time = current_time  # 전송 시간 갱신

        # 스트리밍할 프레임 인코딩
        # 프레임을 JPEG 포맷으로 변환 (HTTP로 전송하기 위함)
        _, buffer = cv2.imencode('.jpg', frame)

        # HTTP 멀티파트 응답 포맷으로 프레임 전송
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')