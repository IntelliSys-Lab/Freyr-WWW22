import matplotlib.pyplot as plt
import os


class Plotter():
    """
    Plot trend for each episode
    """
    def __init__(
        self,
        fig_path=os.path.dirname(os.getcwd())+"/serverless/figures/"
    ):
        self.fig_path = fig_path
    
    def plot_save(
        self,
        prefix_name,
        reward_trend, 
        avg_slow_down_trend=None, 
        avg_completion_time_trend,
        timeout_num_trend,
        loss_trend=None
    ):
        fig_1 = plt.figure('Total Reward Trend', figsize=(6,4)).add_subplot(111)
        fig_1.plot(reward_trend)
        fig_1.set_xlabel("Episode")
        fig_1.set_ylabel("Total reward")
        plt.savefig(self.fig_path + prefix_name + "_Total_Reward_Trend.png")
        plt.clf()
        
        if avg_slow_down_trend is not None:
            fig_2 = plt.figure('Avg Slow Down Trend', figsize=(6,4)).add_subplot(111)
            fig_2.plot(avg_slow_down_trend)
            fig_2.set_xlabel("Episode")
            fig_2.set_ylabel("Avg slow down")
            plt.savefig(self.fig_path + prefix_name + "_Avg_Slow_Down_Trend.png")
            plt.clf()
        
        fig_3 = plt.figure('Avg Completion Time Trend', figsize=(6,4)).add_subplot(111)
        fig_3.plot(avg_completion_time_trend)
        fig_3.set_xlabel("Episode")
        fig_3.set_ylabel("Avg Completion Time")
        plt.savefig(self.fig_path + prefix_name + "_Avg_Completion_Time_Trend.png")
        plt.clf()

        fig_4 = plt.figure('Timeout Num Trend', figsize = (6,4)).add_subplot(111)
        fig_4.plot(timeout_num_trend)
        fig_4.set_xlabel("Episode")
        fig_4.set_ylabel("Timeout num")
        plt.savefig(self.fig_path + prefix_name + "_Timeout_Num_Trend.png")
        plt.clf()
        
        if loss_trend is not None:
            fig_4 = plt.figure('Loss Trend', figsize = (6,4)).add_subplot(111)
            fig_4.plot(loss_trend)
            fig_4.set_xlabel("Episode")
            fig_4.set_ylabel("Loss")
            plt.savefig(self.fig_path + prefix_name + "_Loss_Trend.png")
        
    def plot_show(
        self,
        reward_trend, 
        avg_slow_down_trend=None, 
        avg_completion_time_trend,
        timeout_num_trend,
        loss_trend=None
    ):
        fig_1 = plt.figure('Total Reward Trend', figsize=(6,4)).add_subplot(111)
        fig_1.plot(reward_trend)
        fig_1.set_xlabel("Episode")
        fig_1.set_ylabel("Total reward")
        
        if avg_slow_down_trend is None:
            fig_2 = plt.figure('Avg Slow Down Trend', figsize=(6,4)).add_subplot(111)
            fig_2.plot(avg_slow_down_trend)
            fig_2.set_xlabel("Episode")
            fig_2.set_ylabel("Avg slow down")
        
        fig_3 = plt.figure('Avg Completion Time Trend', figsize=(6,4)).add_subplot(111)
        fig_3.plot(avg_completion_time_trend)
        fig_3.set_xlabel("Episode")
        fig_3.set_ylabel("Avg Completion Time")
        plt.savefig(self.fig_path + prefix_name + "_Avg_Completion_Time_Trend.png")
        plt.clf()

        fig_4 = plt.figure('Timeout Num Trend', figsize=(6,4)).add_subplot(111)
        fig_4.plot(timeout_num_trend)
        fig_4.set_xlabel("Episode")
        fig_4.set_ylabel("Timeout num")
        
        if loss_trend is not None:
            fig_4 = plt.figure('Loss Trend', figsize = (6,4)).add_subplot(111)
            fig_4.plot(loss_trend)
            fig_4.set_xlabel("Episode")
            fig_4.set_ylabel("Loss")
        
        plt.show()
        

