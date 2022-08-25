import os
import torch
from torch.nn import functional as F
import concurrent.futures
 
import pytorch_lightning as pl
#from pytorch_lightning.strategies import DDPStrategy
from ray_lightning import RayPlugin
 
#from pytorch_lightning.plugins.environments.lightning_environment import LightningEnvironment
from pl_bolts.datamodules.mnist_datamodule import MNISTDataModule

import ray
 
 
class LitClassifier(pl.LightningModule):
    def __init__(self, hidden_dim: int = 128, learning_rate: float = 0.0001):
        super().__init__()
        self.save_hyperparameters()
 
        self.l1 = torch.nn.Linear(28 * 28, self.hparams.hidden_dim)
        self.l2 = torch.nn.Linear(self.hparams.hidden_dim, 10)
 
    def forward(self, x):
        x = x.view(x.size(0), -1)
        x = torch.relu(self.l1(x))
        x = torch.relu(self.l2(x))
        return x
 
    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)
        loss = F.cross_entropy(y_hat, y)
        return loss
 
    def validation_step(self, batch, batch_idx):
        x, y = batch
        probs = self(x)
        # we currently return the accuracy as the validation_step/test_step is run on the IPU devices.
        # Outputs from the step functions are sent to the host device, where we calculate the metrics in
        # validation_epoch_end and test_epoch_end for the test_step.
        acc = self.accuracy(probs, y)
        return acc
 
    def test_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        acc = self.accuracy(logits, y)
        return acc
 
    def accuracy(self, logits, y):
        # currently IPU poptorch doesn't implicit convert bools to tensor
        # hence we use an explicit calculation for accuracy here. Once fixed in poptorch
        # we can use the accuracy metric.
        acc = torch.sum(torch.eq(torch.argmax(logits, -1), y).to(torch.float32)) / len(y)
        return acc
 
    def validation_epoch_end(self, outputs) -> None:
        # since the training step/validation step and test step are run on the IPU device
        # we must log the average loss outside the step functions.
        self.log("val_acc", torch.stack(outputs).mean(), prog_bar=True)
 
    def test_epoch_end(self, outputs) -> None:
        self.log("test_acc", torch.stack(outputs).mean())
 
    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=self.hparams.learning_rate)
 
if __name__ == "__main__":
    dm = MNISTDataModule(batch_size=32)
    # pytorch lightning model
    model = LitClassifier()
    plugin = RayPlugin(num_workers=100, use_gpu = False, num_cpus_per_worker=1)

    # os.environ['WORLD_SIZE'] = os.environ['OMPI_COMM_WORLD_SIZE']
    # os.environ['RANK'] = os.environ['OMPI_COMM_WORLD_RANK']
    # os.environ['LOCAL_RANK'] = os.environ['OMPI_COMM_WORLD_LOCAL_RANK']
    # os.environ["NODE_RANK"] = os.environ["OMPI_COMM_WORLD_NODE_RANK"]

    #os.environ['MASTER_ADDR'] = '10.0.1.164'
    # os.environ["MASTER_ADDR"] = ray.get(
    #         self.workers[0].get_node_ip.remote())
    # os.environ["MASTER_PORT"] = str(
    #         ray.get(self.workers[0].execute.remote(find_free_port)))
 
    num_nodes = 2
    num_gpus = 8
 
    # env = LightningEnvironment()
    # env.world_size = lambda: int(os.environ.get("WORLD_SIZE", 0))
    # env.global_rank = lambda: int(os.environ.get("RANK", 0))
    ray.shutdown()
    ray.init(address='auto')
    
    # ddp = DDPStrategy()
        # cluster_environment=env, 
        # process_group_backend="gloo", 
        # accelerator="cpu")
 
    trainer = pl.Trainer(max_epochs=200, num_nodes=num_nodes, plugins=[plugin])
    trainer.fit(model, datamodule=dm)
    trainer.test(model, datamodule=dm)