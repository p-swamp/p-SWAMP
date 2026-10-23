# k8s

The p-swamp stack as Kubernetes manifests, laid out for
[kustomize](https://kustomize.io), which is built into `kubectl`, so there is
nothing to install.

```
k8s/
  base/                 the stack, for any cluster: five Deployments, their Services, two ConfigMaps
    p-swamp.yaml        the manifests; the header says what each object is
    kustomization.yaml  lists them and generates the live feed's ConfigMap
  components/hosts/     a helper for overlays that rename the stack
  overlays/minikube/    the base plus a NodePort: `uv run pswamp deploy minikube`
```

## Why a base and overlays

The stack is described once, in `base/`, without anything that belongs to a
particular cluster. Each place that runs it adds a small *overlay*: a folder
with a `kustomization.yaml` that points at the base and says what is different
for that cluster. `overlays/minikube` is the one for local testing, and it only
adds a fixed port for the browser.

A deployment on another cluster keeps its overlay with the deployment, not in
this repo. The overlay refers to `k8s/base` at a commit of this repo, so the
deployment runs exactly what that commit describes, and upgrading means moving
to a newer commit. The settings, resources and parts of the stack stay here,
and the same manifests run on minikube and in the cloud.

What an overlay typically changes:

- namespace
- name suffix (to run several copies side by side)
- image and registry
- node placement
- ingress and hostname
- extra labels

An overlay can change any field of any object, but most changes apply to all
objects at once, so it rarely needs to know the parts of the stack. It does rely
on a few things, marked "Overlays:" in `base/p-swamp.yaml`: the server's Service
and port names, the image name, the selectors and `p-swamp-hosts` (below).

## Environment variables

Most environment variables are plain settings and can be changed freely. The
exception is a value that contains another Service's name. An overlay may rename
every object, for example to run two copies of the stack in one namespace, and
kustomize updates references between objects but not names inside strings. A
value such as `p-swamp-kafka:9092` would then still point at the original Kafka.

Service names are therefore written only in the `p-swamp-hosts` ConfigMap, and
containers build their values from it. An overlay that renames the stack
includes `components/hosts`, which writes the new names into that ConfigMap. A
new Service that pods connect to needs an entry in both places.

```yaml
envFrom:
  - configMapRef:
      name: p-swamp-hosts          # defines PSWAMP_KAFKA_HOST
env:
  - name: KAFKA_BOOTSTRAP_SERVERS
    value: $(PSWAMP_KAFKA_HOST):9092
```

## Kustomize cheat-sheet

Kustomize renders a directory into plain YAML on your machine, and the cluster only
ever sees the result. In the usual `kubectl` commands, `-k DIR` takes the
place of `-f FILE`.

```sh
kubectl kustomize k8s/overlays/minikube           # print what would be applied
kubectl diff -k k8s/overlays/minikube             # compare with what is running
kubectl apply -k k8s/overlays/minikube            # create or update
kubectl get -k k8s/overlays/minikube              # the objects it manages
kubectl delete -k k8s/overlays/minikube           # remove them
kubectl get pods -l app=p-swamp-kafka             # one part, by its label
```

`kubectl apply` creates and updates objects, but it does not delete an object
that is no longer in the rendered output. A Deployment you remove or rename keeps
running until you delete it yourself.

Here are some of the fields of a `kustomization.yaml` that an overlay may use:

```yaml
resources:            # manifests or other kustomization dirs to start from
  - ../../base
namespace: demo       # set on every object
nameSuffix: -a        # p-swamp-kafka -> p-swamp-kafka-a, references follow
labels:               # added to every object (and to selectors, with includeSelectors)
  - pairs: {app.kubernetes.io/instance: a}
    includeSelectors: true
images:               # swap an image by name, without editing the manifests
  - name: p-swamp
    newName: registry.example.com/p-swamp
    newTag: main-<sha>
patches:              # change fields of one object
  - target: {kind: Service, name: p-swamp}
    patch: |
      - op: replace
        path: /spec/type
        value: NodePort
configMapGenerator:   # a ConfigMap built from files; its hashed name changes with the content, rolling the pods
  - name: p-swamp-pmu-data
    files: [deployment_pmu_data_file_example.txt]
components:           # reusable pieces such as components/hosts
  - ../../components/hosts
```

An overlay can live anywhere and build on this repo straight from GitHub:
`resources: [https://github.com/<owner>/p-SWAMP//k8s/base?ref=<commit>]`.
The [kustomize docs](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/)
describe every field.
