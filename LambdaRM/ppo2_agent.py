import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical
import numpy as np



class PGNet(nn.Module):
    def __init__(
        self, 
        observation_dim, 
        hidden_dims,
        action_dim
    ):
        super(PGNet, self).__init__()
        
        if isinstance(hidden_dims, int):
            hidden_dims = [hidden_dims]
            
        self.layers = []
        
        layer_input = nn.Sequential(
            nn.Linear(observation_dim, hidden_dims[0]),
            nn.Tanh()
        )
        self.layers.append(layer_input)
        
        for i in range(len(hidden_dims)):
            if i == len(hidden_dims)-1:
                layer_output = nn.Linear(hidden_dims[i], action_dim)
                self.layers.append(layer_output)
            else:
                layer_hidden = nn.Sequential(
                    nn.Linear(hidden_dims[i], hidden_dims[i+1]),
                    nn.Tanh()
                )
                self.layers.append(layer_hidden)
        
        self.layer_module = nn.ModuleList(self.layers)
        
    def forward(self, x):
        for layer in self.layer_module:
            x = layer(x)

        return x


class ActorCritic(nn.Module):
    def __init__(
        self, 
        actor,
        critic
    ):
        super().__init__()

        self.actor = actor
        self.critic = critic

    def forward(self, observation):
        action_pred = self.actor(observation)
        value_pred = self.critic(observation)
        
        return action_pred, value_pred


class PPO2Agent():
    def __init__(
        self,
        observation_dim,
        action_dim,
        hidden_dims=64,
        learning_rate=0.01,
        discount_factor=1,
        ppo_clip=0.2,
        ppo_steps=5
    ):
        self.observation_dim = observation_dim
        self.action_dim = action_dim
        self.hidden_dims = hidden_dims
        self.lr = learning_rate
        self.gamma = discount_factor

        self.ppo_clip = ppo_clip
        self.ppo_steps = ppo_steps

        self.observations = []
        self.actions = []
        self.rewards = []
        self.values = []
        self.log_probs = []
        
        self.model = self.build_model()

        self.loss = nn.CrossEntropyLoss()
        # self.optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        self.optimizer = torch.optim.RMSprop(self.model.parameters(), lr=learning_rate)

    def build_model(self):
        actor = PGNet(
            observation_dim=self.observation_dim,
            hidden_dims=self.hidden_dims,
            action_dim=self.action_dim,
        )

        critic = PGNet(
            observation_dim=self.observation_dim,
            hidden_dims=self.hidden_dims,
            action_dim=1,
        )

        ac_model = ActorCritic(actor, critic)

        return ac_model

    def choose_action(self, observation):
        self.model.eval()
        
        action_pred, value_pred = self.model(torch.Tensor(observation[np.newaxis, :]))
        action_prob = F.softmax(action_pred, dim=-1)
        dist = Categorical(action_prob)
        
        action = dist.sample()
        log_prob = dist.log_prob(action)
            
        return action, value_pred, log_prob

    def record_trajectory(self, observation, action, value, reward, log_prob):
        self.observations.append(torch.Tensor(observation[np.newaxis, :]))
        self.actions.append(action)
        self.values.append(value)
        self.rewards.append(reward)
        self.log_probs.append(log_prob)

    def propagate(self):
        self.model.train()
        
        rewards = self.discount_rewards()
        observations = torch.cat(self.observations, dim=0)
        actions = torch.cat(self.actions, dim=0)
        values = torch.cat(self.values).squeeze(-1)
        log_probs = torch.cat(self.log_probs, dim=0)

        advantage = rewards - values
        
        rewards = rewards.detach()
        observations = observations.detach()
        actions = actions.detach()
        log_prob = log_probs.detach()
        advantage = advantage.detach()
        
        loss = 0
        for _ in range(self.ppo_steps):
            # Get new log prob of actions for all input states
            action_pred, value_pred = self.model(observations)
            value_pred = value_pred.squeeze(-1)
            action_prob = F.softmax(action_pred, dim=-1)
            dist = Categorical(action_prob)

            # New log prob using old actions
            new_log_prob = dist.log_prob(actions)

            policy_ratio = (new_log_prob - log_prob).exp()
            policy_loss_1 = policy_ratio * advantage
            policy_loss_2 = torch.clamp(
                policy_ratio, 
                min = 1.0 - self.ppo_clip, 
                max = 1.0 + self.ppo_clip
            ) * advantage

            policy_loss = - torch.min(policy_loss_1, policy_loss_2).mean()
            value_loss = F.smooth_l1_loss(rewards, value_pred).mean()
            loss = loss + policy_loss.item() + value_loss.item()

            self.optimizer.zero_grad()
            policy_loss.backward()
            value_loss.backward()
            self.optimizer.step()

        loss = loss / self.ppo_steps
        return loss
    
    def norm(self, x):
        x = x - np.mean(x)
        x = x / np.std(x)

        return x

    def discount_rewards(self):
        discounted_rewards = []
        tmp = 0
        for reward in self.rewards[::-1]:
            tmp = tmp * self.gamma + reward
            discounted_rewards.append(tmp)
        
        discounted_rewards = torch.Tensor(discounted_rewards[::-1])

        return discounted_rewards
    
    def reset(self):
        self.observations = []
        self.actions = []
        self.values = []
        self.rewards = []
        self.log_probs = []

    def save(self, save_path):
        torch.save(self.model.state_dict(), save_path)

    def load(self, checkpoint_path):
        self.model.load_state_dict(torch.load(checkpoint_path))
