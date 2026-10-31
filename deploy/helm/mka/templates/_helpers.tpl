{{- define "mka.name" -}}{{ .Release.Name }}-mka{{- end -}}
{{- define "mka.labels" -}}
app.kubernetes.io/name: mka
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}
{{- define "mka.pod" -}}
{{- with .root.Values.imagePullSecrets }}
imagePullSecrets: {{ toYaml . | nindent 2 }}
{{- end }}
securityContext: {{ toYaml .root.Values.podSecurityContext | nindent 2 }}
containers:
  - name: {{ .component }}
    image: "{{ .root.Values.image.repository }}:{{ .root.Values.image.tag }}"
    imagePullPolicy: {{ .root.Values.image.pullPolicy }}
    {{- with .command }}
    command: {{ toYaml . | nindent 6 }}
    {{- end }}
    securityContext: {{ toYaml .root.Values.containerSecurityContext | nindent 6 }}
    envFrom:
      - configMapRef: { name: {{ include "mka.name" .root }} }
      - secretRef: { name: {{ .root.Values.existingSecret }} }
    resources: {{ toYaml .resources | nindent 6 }}
    {{- if .port }}
    ports: [ { name: http, containerPort: 8000 } ]
    readinessProbe: { httpGet: { path: /health, port: http }, periodSeconds: 10 }
    livenessProbe: { httpGet: { path: /health, port: http }, initialDelaySeconds: 30, periodSeconds: 20 }
    {{- end }}
    volumeMounts: [ { name: data, mountPath: /data } ]
volumes:
  - name: data
    {{- if .root.Values.persistence.enabled }}
    persistentVolumeClaim: { claimName: {{ include "mka.name" .root }}-data }
    {{- else }}
    emptyDir: {}
    {{- end }}
{{- end -}}
