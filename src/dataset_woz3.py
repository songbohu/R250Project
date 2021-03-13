import os
import re
import sys
import json
import random
import numpy as np
import torch
import configparser
from torch.autograd import Variable
import config

USE_CUDA = True


class DatasetWoz3(object):
	'''
	data container for woz dataset
	'''
	def __init__(self, percentage=1.0):
		# setup
# 		feat_file = config['DATA']['feat_file']
# 		text_file = config['DATA']['text_file']
# #		dataSplit_file = config['DATA']['dataSplit_file']
# 		vocab_file = config['DATA']['vocab_file']
# 		template_file = config['DATA']['template_file']
		vocab_file ="../resource/woz3/vocab.txt"
		feat_file =	"../resource/woz3/feat.json"
		text_file =	"../resource/woz3/text.json"
		template_file =	"../resource/woz3/template.txt"
		dataSplit_file = "../resource/woz3/data_split/Boo_ResDataSplitRand0925.json"
		# TODO: Look at the code.

		# print("feat_file",  file=sys.stderr)
		# print(feat_file, file=sys.stderr)

		self.template = template_file # for further scoring
		
		# hyper-params
		# TODO: Change it to config.

		# self.batch_size = config.getint('DATA', 'batch_size')
		self.batch_size = config.batch_size
		self.percentage = percentage # percentage of data used
		self.data   = {'train':[],'valid':[],'test':[]} 
#		self.data   = {'train':[],'valid':[],'test_seen':[], 'test_unseen':[]}

		self.data_index  = {'train': 0, 'valid': 0, 'test': 0} # index for accessing data
#		self.data_index  = {'train': 0, 'valid': 0, 'test_seen': 0, 'test_unseen': 0} # index for accessing data

		self.n_batch = {}
		self.shuffle = False

		# load vocab from file
		self._loadVocab(vocab_file) # a list of vocab, andy

		# print("word2index",  file=sys.stderr)
		# print(self.word2index,  file=sys.stderr)

		# set input feature cardinality
		# Songbo: Num of some features in the set?
		self._setCardinality(template_file)

		self.do_size = self.dfs[1] - self.dfs[0] # domiain
		self.da_size = self.dfs[2] - self.dfs[1] # dialogue act
		self.sv_size = self.dfs[3] - self.dfs[2] # dialogue act and slot values
		
		# initialise dataset
		self._setupData(text_file, feat_file, dataSplit_file)
		self.reset()

 
	def reset(self):
		self.data_index  = {'train': 0, 'valid': 0, 'test': 0}
#		self.data_index  = {'train': 0, 'valid': 0, 'test_seen': 0, 'test_unseen': 0}
		if self.shuffle:
			random.shuffle(self.data['train'])


	def next_batch(self, data_type='train'):

		def indexes_from_sentence(sentence, add_eos=False):
			indexes = [self.word2index[word] if word in self.word2index else self.word2index['UNK_token'] for word in sentence.split(' ')]
			if add_eos:
				return indexes + [self.word2index['EOS_token']]
			else:
				return indexes

		# Pad a with the PAD symbol
		def pad_seq(seq, max_length):
			seq += [self.word2index['PAD_token'] for i in range(max_length - len(seq))]
			return seq

		# turn list of word indexes into 1-hot matrix
		def getOneHot(indexes):
			res = []
			for index in indexes:
				hot = [0]*len(self.word2index)
				hot[index] = 1
				res.append(hot)
			return res

		# Counter for the data potions.
		# reading a batch
		start = self.data_index[data_type]
		end = self.data_index[data_type] + self.batch_size
		data = self.data[data_type][start:end]
		self.data_index[data_type] += self.batch_size
		indexes = [i for i in range(start, end)]

		sentences, refs, feats, featStrs = [], [], [], []
#		do_label, da_label, sv_label, sv_seqs = [], [], [], []
		sv_indexes = []

		for dial_idx, turn_idx, text, meta in data:

			# Songbo: Here is the place to use ori text than the delex text.
			text_ori, text_delex = text['ori'], text['delex']
			sentences.append(indexes_from_sentence(text_delex, add_eos=True))
			refs.append(text_delex)

			# get semantic feature
			do_idx, da_idx, sv_idx, featStr = self.getFeatIdx(meta)

			# print("do_idx",  file=sys.stderr)
			# print(do_idx,  file=sys.stderr)
			# print("da_idx",  file=sys.stderr)
			# print(da_idx,  file=sys.stderr)
			# print("sv_idx",  file=sys.stderr)
			# print(sv_idx,  file=sys.stderr)
			# print("featStr",  file=sys.stderr)
			# print(featStr,  file=sys.stderr)

			# do_idx
			# [6, 1]
			# da_idx
			# [30, 5]
			# sv_idx
			# [552, 131, 127, 126, 130]
			# featStr
			# Booking - OfferBooked - Day - 1 | Booking - OfferBooked - Name - 1 | Booking - OfferBooked - People - 1 | Booking - OfferBooked - Ref - 1 | general - reqmore - none - none

			do_cond = [1 if i in do_idx else 0 for i in range(self.do_size)] # domain condition
			da_cond = [1 if i in da_idx else 0 for i in range(self.da_size)] # dial act condition
			sv_cond = [1 if i in sv_idx else 0 for i in range(self.sv_size)] # slot/value condition




			feats.append(do_cond + da_cond + sv_cond)
			featStrs.append(featStr)

#			# get labels for da, slots
#			do_label.append(do_cond)
#			da_label.append(da_cond)
#			sv_label.append(sv_cond)
			sv_indexes.append(sv_idx)

		# Zip into pairs, sort by length (descending), unzip
		# Note: _words and _seqs should be sorted in the same order
		seq_pairs = sorted(zip(sentences, refs, feats, featStrs, sv_indexes), key=lambda p: len(p[0]), reverse=True)



		sentences, refs, feats, featStrs, sv_indexes = zip(*seq_pairs)

		# print("sentences", file=sys.stderr)
		# print(len(sentences), file=sys.stderr)
		# print((sentences[0]), file=sys.stderr)
		# print(list(map(lambda x : self.index2word[x], sentences[0])), file=sys.stderr)
		#

		# Pad with 0s to max length
		lengths = [len(s) for s in sentences]
		sentences_padded = [pad_seq(s, max(lengths)) for s in sentences]

		# Turn (batch_size, max_len) into (batch_size, max_len, n_vocab)
		sentences = [getOneHot(s) for s in sentences_padded]

		input_var = Variable(torch.FloatTensor(sentences))
		label_var = Variable(torch.LongTensor(sentences_padded))

		# print("label_var", file=sys.stderr)
		# print((label_var), file=sys.stderr)


		feats_var = Variable(torch.FloatTensor(feats))
#		do_label = Variable(torch.FloatTensor(do_label))
#		da_label = Variable(torch.FloatTensor(da_label))
#		sv_label = Variable(torch.FloatTensor(sv_label))

		if USE_CUDA:
			input_var = input_var.cuda()
			label_var = label_var.cuda()
			feats_var = feats_var.cuda()
#			do_label = do_label.cuda()
#			da_label = da_label.cuda()
#			sv_label = sv_label.cuda()

		return input_var, label_var, feats_var, lengths, refs, featStrs, sv_indexes
#		return target_var, target_lengths, target_label, feats_var, words, featStrs, do_label, da_label, sv_label, sv_seqs


	def _setCardinality(self, template_file):
		self.cardinality = []
		with open(template_file) as f:
#			self.dfs = [0,0,0]
			self.dfs = [0,0,0,0]
			for line in f.readlines():
				self.cardinality.append(line.replace('\n',''))
				if line.startswith('d:'):
					self.dfs[1]+=1
				elif line.startswith('d-a:'):
					self.dfs[2]+=1
				elif line.startswith('d-a-s-v:'):
					self.dfs[3]+=1
			for i in range(0, len(self.dfs)-1):
				self.dfs[i+1] = self.dfs[i] + self.dfs[i+1]


	def printDataInfo(self):
		print('***** DATA INFO *****')
		print('Using {}% of training data'.format(self.percentage*100))
		print('BATCH SIZE:', self.batch_size)
		
		print('Train:', len(self.data['train']), 'turns')
		print('Valid:', len(self.data['valid']), 'turns')
		print('Test:', len(self.data['test']), 'turns')
#		print('Test (seen):', len(self.data['test_seen']))
#		print('Test (unseen):', len(self.data['test_unseen']))
		print('# of turns', file=sys.stderr)
		print('Train:', len(self.data['train']), file=sys.stderr)
		print('Valid:', len(self.data['valid']), file=sys.stderr)
		print('Test:', len(self.data['test']), file=sys.stderr)
#		print('Test (seen):', len(self.data['test_seen']), file=sys.stderr)
#		print('Test (unseen):', len(self.data['test_unseen']), file=sys.stderr)
		print('# of batches: Train {} Valid {} Test {}'.format(self.n_batch['train'], self.n_batch['valid'], self.n_batch['test']))
		print('# of batches: Train {} Valid {} Test {}'.format(self.n_batch['train'], self.n_batch['valid'], self.n_batch['test']), file=sys.stderr)
		print('*************************\n')


	def _setupData(self, text_file, feat_file, dataSplit_file):
		with open(text_file) as f:
			dial2text = json.load(f)
		with open(feat_file) as f:
			dial2meta = json.load(f)

		with open(dataSplit_file) as f:
			dataSet_split = json.load(f)


		# print("dial2text",  file=sys.stderr)
		# print(dial2text,  file=sys.stderr)


		for data_type in ['train', 'valid', 'test']:
#		for data_type in ['train', 'valid', 'test_seen', 'test_unseen']:
			for dial_idx, turn_idx, _ in dataSet_split[data_type]:
				# might have empty feat turn which is not in feat file
				if turn_idx not in dial2meta[dial_idx]:
					continue

				meta = dial2meta[dial_idx][turn_idx]
				text = dial2text[dial_idx][turn_idx]
				self.data[data_type].append((dial_idx, turn_idx, text, meta))

		# percentage of training data
		if self.percentage < 1:
			_len = len(self.data['train'])
			self.data['train'] = self.data['train'][:int(_len*self.percentage)]

		# setup number of batch
		for _type in ['train', 'valid', 'test']:
#		for _type in ['train', 'valid', 'test_seen', 'test_unseen']:
			self.n_batch[_type] = len(self.data[_type]) // self.batch_size

		# self.printDataInfo()


	
	def _loadVocab(self,vocab_file):
		# load vocab
		self.word2index = {}
		self.index2word = {}
		idx = 0
		with open(vocab_file) as fin:
			for word in fin.readlines():
				word = word.strip().split('\t')[0]
				self.word2index[word] = idx
				self.index2word[idx] = word
				idx += 1


	def getFeatIdx(self, meta):
		feat_container = []
		do_idx, da_idx, sv_idx = [], [], []
		for da, slots in meta.items():
			do = da.split('-')[0]
			_do_idx = self.cardinality.index('d:'+do) - self.dfs[0]
			if _do_idx not in do_idx:
				do_idx.append(_do_idx)
			da_idx.append( self.cardinality.index('d-a:'+da) - self.dfs[1] )
			for _slot in slots: # e.g. ('Day', '1', 'Wednesday ')
				sv_idx.append( self.cardinality.index('d-a-s-v:'+da+'-'+_slot[0]+'-'+_slot[1]) - self.dfs[2] )
				feat_container.append( da+'-'+_slot[0]+'-'+_slot[1] )

		feat_container = sorted(feat_container) # sort SVs across DAs to make sure universal order
		feat = '|'.join(feat_container)

		return do_idx, da_idx, sv_idx, feat
